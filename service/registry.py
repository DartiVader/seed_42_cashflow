"""Реестр версий моделей (models/<модель>-<vN>) и отчёты (reports/*.csv)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from service.store import Store, now

REPORTS = {"model_comparison", "ablation", "oracle", "experiments"}
VERSION_RE = re.compile(r"^[a-z_]+-v\d+$")
ACTIVE_KEY = "active_model"


def versions(models_dir: Path) -> list[str]:
    return sorted(p.name for p in Path(models_dir).iterdir() if (p / "meta.json").exists() and VERSION_RE.match(p.name))


def active_version(store: Store, default: str) -> str:
    return store.get_kv(ACTIVE_KEY, default)


def _csv(reports_dir: Path, name: str) -> pd.DataFrame | None:
    p = Path(reports_dir) / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else None


def _num(x):
    return None if x is None or pd.isna(x) else round(float(x), 4)


def metrics(models_dir: Path, reports_dir: Path, version: str) -> dict:
    """metrics.json версии (пишет retrain) приоритетнее; иначе — best-effort из reports/: MAE остатка из
    model_comparison, разрывы (counterfactual) и Brier из ablation по строке события версии, покрытие из
    gap_metrics. Чего нет — null."""
    keys = ("mae_d7", "mae_d30", "cf_recall", "cf_precision", "coverage", "brier")
    out = dict.fromkeys(keys)
    own = Path(models_dir) / version / "metrics.json"
    if own.exists():
        return {**out, **json.loads(own.read_text(encoding="utf-8"))}
    meta = json.loads((Path(models_dir) / version / "meta.json").read_text(encoding="utf-8"))
    mc = _csv(reports_dir, "model_comparison")
    if mc is not None:
        r = mc[(mc["model"] == meta["name"]) & (mc["company_set"] == "new_dates") & (mc["period"] == "report")]
        if len(r):
            out["mae_d7"], out["mae_d30"] = _num(r.iloc[0]["mae_bal_d7"]), _num(r.iloc[0]["mae_bal_d30"])
    ev = Path(models_dir) / version / "events.json"
    ab = _csv(reports_dir, "ablation")
    if ev.exists() and ab is not None:
        row = json.loads(ev.read_text(encoding="utf-8")).get("residual_model")
        r = ab[(ab["row"] == row) & (ab["company_set"] == "new_dates")]
        if len(r):
            out["cf_recall"], out["cf_precision"] = _num(r.iloc[0]["counterfactual_recall"]), _num(r.iloc[0]["counterfactual_precision"])
            out["brier"] = _num(r.iloc[0]["counterfactual_brier_cal"])
    gm = _csv(reports_dir, "gap_metrics")
    if gm is not None:
        r = gm[(gm["model"] == meta["name"]) & (gm["company_set"] == "new_dates") & (gm["period"] == "report")]
        if len(r):
            out["coverage"] = _num(r["coverage_p10_p90"].mean())
    return out


def describe(store: Store, models_dir: Path, reports_dir: Path, default: str) -> list[dict]:
    act = active_version(store, default)
    res = []
    for v in versions(models_dir):
        tr = Path(models_dir) / v / "training.json"
        trained = json.loads(tr.read_text(encoding="utf-8")).get("trained_until") if tr.exists() else None
        res.append({"version": v, "active": v == act, "trained_at": trained,
                    "metrics": metrics(models_dir, reports_dir, v)})
    return res


def report(reports_dir: Path, name: str) -> dict | None:
    if name not in REPORTS:
        return None
    df = _csv(reports_dir, name)
    if df is None:
        return None
    df = df.astype(object).where(df.notna(), None)
    return {"columns": list(df.columns), "rows": df.values.tolist()}


def next_version(models_dir: Path, model: str = "lgbm_net") -> str:
    nums = [int(v.rsplit("-v", 1)[1]) for v in versions(models_dir) if v.startswith(model + "-v")]
    return f"{model}-v{max(nums, default=0) + 1}"


def run_retrain_job(db_path: str, job_id: str, data_dir: str, models_dir: str, state_dir: str) -> None:
    """Обучение + backtest (python -m ml.train) в подпроцессе. Отчёты — в state_dir, чтобы не затирать reports/.
    Новая версия не активируется сама: admin вызывает POST /ml/models/{v}/activate."""
    st = Store(Path(db_path))
    version = next_version(Path(models_dir))
    ver = version.rsplit("-", 1)[1]
    st.update_job(job_id, status="running", started_at=now(), stage="train", progress=0.05)
    out_dir = Path(state_dir) / "retrain" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "ml.train", "--data", data_dir, "--models-dir", models_dir,
           "--reports", str(out_dir), "--version", ver, "--events", "mandatory"]
    with open(out_dir / "train.log", "wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(5)
            st.update_job(job_id, progress=min(0.9, (st.get_job(job_id)["progress"] or 0) + 0.01))
    if proc.returncode == 0 and (Path(models_dir) / version / "meta.json").exists():
        st.update_job(job_id, status="done", stage="ready", progress=1.0, finished_at=now())
    else:
        st.update_job(job_id, status="failed", finished_at=now(),
                      error={"code": "retrain_failed", "message": "Обучение не завершилось. Подробности — в логе сервиса."})
