"""Код, который исполняется в дочерних процессах (ProcessPoolExecutor, spawn).

Воркер прогноза держит свой ForecastContext. Активная версия модели приезжает с каждым запросом:
если она сменилась (POST /ml/models/{v}/activate) — воркер перегружает контекст перед расчётом.
Логи: только company_id, количества, тайминги.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger("ml.worker")

_CTX = None
_VERSION: str | None = None
_PATHS: tuple[str, str, str] | None = None


def split_version(version: str) -> tuple[str, str]:
    model, _, ver = version.rpartition("-")
    return model, ver


def _load(version: str) -> None:
    global _CTX, _VERSION
    from ml.forecast.api import ForecastContext
    data_dir, models_dir, reports_dir = _PATHS
    model, ver = split_version(version)
    t = time.perf_counter()
    _CTX = ForecastContext.load(data_dir, models_dir, Path(reports_dir) / "backtest_residuals.parquet",
                                model=model, version=ver)
    _VERSION = version
    log.info("context loaded version=%s companies=%d sec=%.1f", version, _CTX.companies["company_id"].nunique(),
             time.perf_counter() - t)


def init_worker(data_dir: str, models_dir: str, reports_dir: str, version: str) -> None:
    global _PATHS
    _PATHS = (data_dir, models_dir, reports_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load(version)


def _ctx(version: str):
    if version != _VERSION:
        _load(version)
    return _CTX


def ping(version: str) -> dict:
    ctx = _ctx(version)
    return {"model_version": ctx.model_version}


def _scenario(d: dict | None):
    from ml.forecast.contracts import Scenario
    if not d:
        return None
    return Scenario(delay_counterparty=d.get("delay_counterparty") or {},
                    revenue_multiplier=d.get("revenue_multiplier", 1.0),
                    fixed_cost_multiplier=d.get("fixed_cost_multiplier", 1.0),
                    extra_expenses=[_event(e) for e in d.get("extra_expenses") or []])


def _event(d: dict):
    from ml.forecast.contracts import Event
    return Event(date=date.fromisoformat(d["date"]), amount=d["amount"], category=d["category"],
                 source=d.get("source", "manual"), confidence=d.get("confidence", 1.0),
                 mandatory=d.get("mandatory", False), stream_id=d.get("stream_id"))


def _statement(company_id: str, as_of: date, ctx, user_id: int | None = None
               ) -> tuple[pd.DataFrame | None, str | None]:
    """Выписка из БД (get_operations_period) или None — тогда forecast() берёт операции из CSV-контекста.

    Без DATABASE_URL — прежний режим (CSV). Компания без операций в БД, но есть в датасете — тоже из контекста,
    кроме запроса для пользователя (user_id): чужие данные датасета ему не подставляем.
    """
    from ml.forecast.contracts import ForecastError
    from service.db import db_enabled, fetch_statement
    if not db_enabled():
        return None, None
    ops, industry = fetch_statement(company_id, as_of, user_id)
    if not ops.empty:
        return ops, industry
    if user_id is None and (ctx.companies["company_id"] == company_id).any():
        return None, None
    raise ForecastError(f"Нет данных по компании {company_id} на {as_of:%d.%m.%Y}")


def run_forecast(version: str, company_id: str, req: dict, user_id: int | None = None) -> dict:
    from ml.forecast.api import forecast
    ctx = _ctx(version)
    if req.get("threshold"):
        # порог разрыва — на запрос, общий контекст не трогаем
        ctx = replace(ctx, gap=replace(ctx.gap, threshold=float(req["threshold"])))
    as_of = date.fromisoformat(req["as_of"])
    ops, industry = _statement(company_id, as_of, ctx, user_id)
    res = forecast(company_id, as_of, req["horizon_days"],
                   events=[_event(e) for e in req.get("events") or []], scenario=_scenario(req.get("scenario")),
                   seed=req["seed"], context=ctx, ops=ops, industry=industry)
    out = res.to_dict()
    # to_dict() не отдаёт mandatory событий, а контракт (п. 2) его требует
    for raw, ev in zip(out["events"], res.events):
        raw["mandatory"] = bool(ev.mandatory)
        raw.setdefault("counterparty_name", None)
        raw.setdefault("overdue_from", None)
    return out


def run_plan_fact(version: str, company_id: str, as_of: str, lookback_days: int, user_id: int | None = None) -> dict:
    from ml.forecast.plan_fact import plan_fact
    ctx = _ctx(version)
    day = date.fromisoformat(as_of)
    ops, _industry = _statement(company_id, day, ctx, user_id)
    return plan_fact(company_id, day, lookback_days, context=ctx, ops=ops)


# ------------------------------------------------------------------ фоновые задачи (отдельный пул)

_OPS: pd.DataFrame | None = None


def _ops(data_dir: str) -> pd.DataFrame:
    global _OPS
    if _OPS is None:
        from ml.data.loaders import load_dataset
        from ml.pipeline.clean import clean_operations
        ops, _ = load_dataset(data_dir)
        _OPS = clean_operations(ops)
    return _OPS


def run_process_job(db_path: str, job_id: str, data_dir: str) -> None:
    """clean → categorize → regular → events → ready для одной компании; пишет в ml_categories и ml_streams."""
    from service.store import Store, now
    st = Store(Path(db_path))
    job = st.get_job(job_id)
    company_id, params = job["company_id"], job["params"]

    def step(stage: str, progress: float) -> None:
        st.update_job(job_id, stage=stage, progress=progress)

    st.update_job(job_id, status="running", started_at=now(), stage="clean", progress=0.05)
    t = time.perf_counter()
    try:
        ops = _ops(data_dir)
        ops = ops[ops["company_id"] == company_id].reset_index(drop=True)
        if ops.empty:
            raise LookupError("no_data")
        as_of = ops["operation_date"].max()
        from_date = params.get("from_date") if params.get("reason") == "update" else None
        step("categorize", 0.3)
        from ml.pipeline.regular import analyze, to_events
        ra = analyze(ops, as_of.date())
        step("regular", 0.65)
        lab = ra.labels
        part = ops if not from_date else ops[ops["operation_date"] >= pd.Timestamp(from_date)]
        rows = [(r.operation_id, r.operation_date.strftime("%Y-%m-%d"), float(r.signed),
                 lab.at[i, "category"] or "other", 1.0, "rules", int(bool(lab.at[i, "mandatory"])),
                 int(bool(lab.at[i, "is_regular"])), lab.at[i, "stream_id"])
                for i, r in zip(part.index, part.itertuples(index=False))]
        st.replace_operations(company_id, rows, from_date)
        step("events", 0.85)
        st.replace_streams(company_id, _streams(ra, to_events(ra)))
        st.update_job(job_id, status="done", stage="ready", progress=1.0, finished_at=now())
        log.info("process done company=%s ops=%d sec=%.1f", company_id, len(rows), time.perf_counter() - t)
    except Exception as e:                                                    # noqa: BLE001
        log.exception("process failed company=%s", company_id)
        msg = ("Компания не найдена в данных." if isinstance(e, LookupError)
               else "Не удалось обработать выписку. Проверьте файл и загрузите его ещё раз.")
        st.update_job(job_id, status="failed", finished_at=now(),
                      error={"code": "no_data" if isinstance(e, LookupError) else "process_failed", "message": msg})


def _streams(ra, events) -> list[dict]:
    """Потоки для GET /streams: период, день месяца, сумма, обязательность, ближайшая дата."""
    if ra.streams.empty:
        return []
    nxt = {}
    for e in events:
        if e.stream_id and e.stream_id not in nxt:
            nxt[e.stream_id] = e
    last = ra.payments.groupby("stream_id")["operation_date"].max() if not ra.payments.empty else {}
    out = []
    for s in ra.streams.itertuples(index=False):
        sid = s.stream_id
        ev = nxt.get(sid)
        months = max(1, int(getattr(s, "months_ahead", 1) or 1))
        raw_next = getattr(s, "predicted_next_date_raw", None)
        nd = ev.date if ev else (pd.Timestamp(raw_next).date() if raw_next is not None and pd.notna(raw_next) else None)
        out.append({
            "stream_id": sid, "category": s.category,
            "period": "month" if months == 1 else f"{months}_months",
            "day": nd.day if nd else None,
            "amount": round(float(s.predicted_amount) * (1 if "поступл" in str(s.direction) else -1), 2),
            "mandatory": bool(s.mandatory), "confidence": round(float(getattr(s, "gap_conf", 1.0)), 2),
            "last_date": pd.Timestamp(last[sid]).strftime("%Y-%m-%d") if sid in last else None,
            "next_date": nd.isoformat() if nd else None})
    return out
