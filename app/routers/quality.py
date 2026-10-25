"""Отчёт о качестве модели (контрольный прогон ML): JSON-сводка, таблицы CSV и картинки PNG.

Два отчёта (параметр source):
  admin   — по компаниям, загруженным администраторами: ML-шлюз выгружает их из БД, запускает ml.evaluation.control
            и отмечает готовый отчёт в <QUALITY_DIR>/latest.json. Пересчёт запускает администратор (и сам бэкенд
            после загрузки данных администратором);
  dataset — прежний контрольный прогон по датасету участников: <REPORTS_DIR>/control.
Картинки — только из белого списка: name.png в папке выбранного отчёта.
"""
import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from app.config import Settings, get_settings
from app.responses import ApiError, ok
from app.security import CurrentUser, admin_user, current_user

log = logging.getLogger("backend.quality")
router = APIRouter(prefix="/api/quality", tags=["quality"])

SAFE_PNG = re.compile(r"^[A-Za-z0-9_.-]+\.png$")
MAX_TABLE_ROWS = 500


def latest_report(settings: Settings) -> tuple[Path | None, dict]:
    """Папка последнего отчёта из latest.json и его описание (компаний, когда посчитан)."""
    root = Path(settings.quality_dir)
    try:
        latest = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        folder = (root / latest["report"]).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return None, {}
    if not folder.is_relative_to(root.resolve()) or not folder.is_dir():
        return None, {}
    return folder, latest


def cell(value: str) -> str | float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return value


def read_table(path: Path) -> dict:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {"columns": [], "rows": []}
    return {"columns": rows[0], "rows": [[cell(v) for v in row] for row in rows[1:MAX_TABLE_ROWS + 1]]}


def png_paths(folder: Path) -> dict[str, Path]:
    """Картинки отчёта: в корне папки и в figures/ (так их кладёт ml.evaluation.control)."""
    found = {}
    for path in [*folder.glob("figures/*.png"), *folder.glob("*.png")]:
        if SAFE_PNG.match(path.name):
            found[path.name] = path
    return found


def png_names(folder: Path) -> list[str]:
    return sorted(png_paths(folder))


PRODUCT = "v2 (продукт"     # предиктор продукта в metrics_gaps.csv: «v2 (продукт: порог 0,35, isotonic)»
LABELS = {"counterfactual": "shortfall", "strict": "negative"}
BALANCE_FACT = "фактический остаток"


def gap_metrics(row: dict) -> dict:
    keys = ("accuracy", "precision", "recall", "f1", "roc_auc", "brier")
    metrics = {k: float(row[k]) for k in keys if row.get(k) not in (None, "")}
    metrics["confusion"] = {k: int(float(row[k])) for k in ("tp", "fp", "fn", "tn")}
    return metrics


def summary_from_report(folder: Path) -> dict | None:
    """Сводка для страницы из отчёта ml.evaluation.control: metrics_gaps.csv, metrics_balance.csv, summary.md."""
    gaps_path, balance_path = folder / "metrics_gaps.csv", folder / "metrics_balance.csv"
    if not gaps_path.exists():
        return None
    with open(gaps_path, encoding="utf-8-sig", newline="") as f:
        gaps = [r for r in csv.DictReader(f) if r["predictor"].startswith(PRODUCT)]
    summary: dict = {"classification": {}, "classification_holdout": {}}
    for row in gaps:
        target = LABELS.get(row["label"])
        if target and row["segment"] == "all":
            summary["classification"][target] = gap_metrics(row)
        elif target and row["segment"] == "holdout":
            summary["classification_holdout"][target] = gap_metrics(row)
    if balance_path.exists():
        with open(balance_path, encoding="utf-8-sig", newline="") as f:
            balance = [r for r in csv.DictReader(f) if r["fact"] == BALANCE_FACT]
        summary["regression"] = [
            {"horizon": int(r["day"]), "mae": float(r["mae_mean"]), "mse": float(r["mse_mean"]),
             "rmse": float(r["rmse_mean"]),
             **({"coverage_p10_p90": float(r["coverage_p10_p90"])} if r.get("coverage_p10_p90") else {})}
            for r in balance if r["predictor"] == "v2 P50"]
        models: dict[str, dict] = {}
        for r in balance:
            models.setdefault(r["predictor"], {"model": r["predictor"]})[f"mae_d{r['day']}"] = float(r["mae_mean"])
        summary["baselines"] = list(models.values())
        companies = next((int(r["companies"]) for r in balance if r["predictor"] == "v2 P50"), None)
    else:
        companies = None
    origins = next((int(r["n"]) for r in gaps if r["segment"] == "all"), None)
    text = (folder / "summary.md").read_text(encoding="utf-8") if (folder / "summary.md").exists() else ""
    model = re.search(r"Модель: `([^`]+)`", text)
    holdout = re.search(r"холдаут\w* компаний \((\d+) шт", text)
    if model:
        summary["model_version"] = model.group(1)
    summary["method"] = {
        "scheme": "Точки прогноза — последний рабочий день каждого месяца; прогноз строится только по данным "
                  "до этой даты и сверяется с тем, что было потом (30 дней факта)",
        "companies": companies, "origins": origins,
        "holdout": f"{holdout.group(1)} компаний, которых модель не видела при обучении" if holdout else None,
    }
    return summary


SOURCES = ("admin", "dataset")


def report_folder(settings: Settings, source: str) -> tuple[Path | None, dict]:
    if source not in SOURCES:
        raise ApiError(400, "Отчёт: admin или dataset", "source")
    if source == "dataset":
        folder = Path(settings.reports_dir) / "control"
        return (folder if folder.is_dir() else None), {}
    return latest_report(settings)


async def quality_job(request: Request) -> dict | None:
    """Последняя задача пересчёта у ML-шлюза; шлюз недоступен — без статуса, отчёт всё равно показываем."""
    try:
        job = (await request.app.state.ml.quality_status()).get("job")
    except ApiError:
        return None
    if not job:
        return None
    error = job.get("error")
    return {"id": job["job_id"], "status": job["status"], "progress": job.get("progress"),
            "startedAt": job.get("started_at"), "finishedAt": job.get("finished_at"),
            "error": error.get("message") if isinstance(error, dict) else None}


async def start_quality_run(request: Request) -> None:
    """Фоновый запуск пересчёта (после загрузки администратором): ошибки — только в лог."""
    try:
        await request.app.state.ml.quality_run()
    except ApiError:
        log.warning("quality run not started: ml unavailable")


@router.get("")
async def get_quality(request: Request, source: str = "admin", user: CurrentUser = Depends(current_user),
                      settings: Settings = Depends(get_settings)) -> JSONResponse:
    folder, latest = report_folder(settings, source)
    meta = {"kind": source, "canRun": user.is_admin, "job": await quality_job(request),
            "source": {"companies": latest.get("companies"), "computedAt": latest.get("finished_at")} if latest else None}
    if folder is None:
        return ok(request, {"available": False, **meta})
    summary = None
    summary_path = folder / "summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("quality summary.json unreadable")
    if summary is None:
        summary = summary_from_report(folder)
    tables = {}
    for path in sorted(folder.glob("*.csv")):
        try:
            tables[path.stem] = read_table(path)
        except (OSError, csv.Error, UnicodeDecodeError):
            log.warning("quality table unreadable: %s", path.name)
    files = [p for p in folder.iterdir() if p.is_file()]
    generated = max((p.stat().st_mtime for p in files), default=None)
    return ok(request, {
        "available": summary is not None or bool(tables),
        "summary": summary,
        "tables": tables,
        "images": png_names(folder),
        "generatedAt": datetime.fromtimestamp(generated).isoformat(timespec="seconds") if generated else None,
        **meta,
    })


@router.post("/run", status_code=202)
async def run_quality(request: Request, user: CurrentUser = Depends(admin_user)) -> JSONResponse:
    result = await request.app.state.ml.quality_run()
    log.info("quality run user_id=%s job_id=%s", user.id, result.get("job_id"))
    return ok(request, {"jobId": result.get("job_id")}, 202)


@router.get("/files/{name}")
async def get_quality_file(name: str, source: str = "admin", user: CurrentUser = Depends(current_user),
                           settings: Settings = Depends(get_settings)) -> FileResponse:
    folder, _latest = report_folder(settings, source)
    images = png_paths(folder) if folder is not None else {}
    if not SAFE_PNG.match(name) or name not in images:
        raise ApiError(404, "Такой картинки в отчёте нет")
    return FileResponse(images[name], media_type="image/png")
