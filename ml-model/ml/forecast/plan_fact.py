"""План-факт: что прогноз lookback_days рабочих дней назад обещал на прошедшие дни и что случилось.

    plan_fact(company_id, as_of, lookback_days=10, seed=42, context=ctx) -> dict

План — forecast() на as_of_plan тем же кодом и той же моделью. Факт — операции и balance_eod ≤ as_of:
всё, что позже as_of, отрезается до любых расчётов.

События плана — регулярные потоки (ml.pipeline.regular) на as_of_plan с датой в (as_of_plan, as_of],
включая не обязательные (поступления клиентов, которые v2 ждёт внутри модели). Событие исполнено, если
в факте есть операции того же потока (ключ контрагента Влада, категория, направление) в окне ±3 рабочих дня
от ожидаемой даты: сумма в ±20% — paid, меньше — partial, ничего — missed (больше плана — тоже paid,
сумма факта видна в amount_fact). days_late — рабочих дней от
ожидаемой даты (у просроченного на as_of_plan — от первой пропущенной) до последней операции,
у missed — до as_of; window_open — окно ещё не закрылось к as_of.
Дополнительно к заданному выходу: deviation в daily, mandatory/confidence/window_open/overdue_from в events,
paid/partial/outside_days/max_deviation_date в summary.

Пропущенные поступления в текущий прогноз переносит сам forecast() (ForecastContext.carry_overdue_receipts):
to_events на as_of видит их как просроченные и ставит событие с overdue_from.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ml.data.calendar import all_working_days
from ml.forecast.api import ForecastContext, forecast
from ml.forecast.contracts import ForecastError
from ml.forecast.panel import build_panel
from ml.forecast.statement import company_row, validate_statement
from ml.pipeline.clean import clean_operations
from ml.pipeline.regular import CLEAN_FLAGS, analyze, to_events

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanFactConfig:
    window_wd: int = 3          # окно поиска факта вокруг ожидаемой даты, рабочих дней
    amount_tol: float = 0.2     # paid, если |факт − план| ≤ 20% плана
    horizon_days: int = 30      # горизонт плана, как у обычного прогноза


def plan_fact(company_id: str, as_of: date, lookback_days: int = 10, seed: int = 42, *,
              context: ForecastContext, ops: pd.DataFrame | None = None,
              config: PlanFactConfig = PlanFactConfig()) -> dict:
    """ops — выписка из запроса (как в forecast); без неё — операции компании из контекста."""
    as_of = pd.Timestamp(as_of).normalize()
    wd = all_working_days()
    end = int(wd.searchsorted(as_of, side="right")) - 1          # последний рабочий день ≤ as_of
    if end - lookback_days < 0:
        raise ForecastError("Слишком большой период для план-факта: календарь начинается позже")
    as_of_plan = wd[end - lookback_days]

    ops_c, comp = _company_ops(company_id, as_of, context, ops)
    plan = forecast(company_id, as_of_plan.date(), config.horizon_days, seed=seed, context=context,
                    ops=None if ops is None else ops[pd.to_datetime(ops["operation_date"]) <= as_of],
                    advice=False)

    daily = _daily(plan, build_panel(ops_c, comp), as_of_plan, as_of)
    events = _events(ops_c, as_of_plan, as_of, wd, config)
    dev = [d for d in daily if d["fact"] is not None]
    worst = max(dev, key=lambda d: abs(d["deviation"]), default=None)
    summary = {
        "missed_in": sum(e["status"] == "missed" and e["amount_plan"] > 0 for e in events),
        "missed_out": sum(e["status"] == "missed" and e["amount_plan"] < 0 for e in events),
        "partial": sum(e["status"] == "partial" for e in events),
        "paid": sum(e["status"] == "paid" for e in events),
        "outside_days": sum(d["outside"] for d in dev),
        "max_deviation": worst["deviation"] if worst else None,
        "max_deviation_date": worst["date"] if worst else None,
    }
    log.info("план-факт %s: дней %d, событий %d, missed %d/%d, вне коридора %d", company_id, len(daily),
             len(events), summary["missed_in"], summary["missed_out"], summary["outside_days"])
    return {"company_id": company_id, "as_of": as_of.date().isoformat(), "as_of_plan": as_of_plan.date().isoformat(),
            "model_version": plan.model_version, "daily": daily, "events": events, "summary": summary}


def _company_ops(company_id: str, as_of: pd.Timestamp, context: ForecastContext,
                 ops: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if ops is not None:
        ops_c = clean_operations(validate_statement(ops, company_id, as_of))
        comp, _ = company_row(company_id, context.companies, None)
    else:
        ops_c = context.ops[context.ops["company_id"] == company_id]
        comp = context.companies[context.companies["company_id"] == company_id]
    # факт после as_of не участвует ни в чём, в том числе в очистке и разметке
    ops_c = ops_c[ops_c["operation_date"] <= as_of]
    return clean_operations(ops_c.drop(columns=list(CLEAN_FLAGS), errors="ignore")), comp


def _daily(plan, panel: pd.DataFrame, as_of_plan: pd.Timestamp, as_of: pd.Timestamp) -> list[dict]:
    # в выходной остаток не меняется: факт — остаток последнего рабочего дня; после конца выписки факта нет
    fact = panel.set_index("date")["balance_eod"]
    wd = all_working_days()
    known_until = wd[wd.searchsorted(panel["date"].max(), side="right")]   # следующий рабочий день — уже без факта
    out = []
    for b in plan.daily:
        d = pd.Timestamp(b.date)
        if not (as_of_plan < d <= as_of):
            continue
        k = int(fact.index.searchsorted(d, side="right")) - 1
        f = float(fact.iloc[k]) if k >= 0 and d < known_until else None
        out.append({"date": d.date().isoformat(), "plan_p10": round(b.p10), "plan_p50": round(b.p50),
                    "plan_p90": round(b.p90), "fact": None if f is None else round(f, 2),
                    "deviation": None if f is None else round(f - b.p50, 2),
                    "outside": None if f is None else bool(f < b.p10 or f > b.p90)})
    return out


def _events(ops_c: pd.DataFrame, as_of_plan: pd.Timestamp, as_of: pd.Timestamp, wd: pd.DatetimeIndex,
            cfg: PlanFactConfig) -> list[dict]:
    ra_plan = analyze(ops_c, as_of_plan.date(), cfg.horizon_days)
    planned = [e for e in to_events(ra_plan, cfg.horizon_days) if as_of_plan < pd.Timestamp(e.date) <= as_of]
    if not planned:
        return []
    streams = ra_plan.streams.set_index("stream_id")
    # факт: операции (as_of_plan, as_of], разметка и ключи контрагентов — кодом Влада на as_of
    ra_fact = analyze(ops_c, as_of.date(), cfg.horizon_days)
    biz = ~ops_c[list(CLEAN_FLAGS)].any(axis=1)
    f = ops_c[biz & (ops_c["operation_date"] > as_of_plan)].assign(
        key=ra_fact.counterparty_key, cat=ra_fact.labels["category"],
        inflow=lambda o: o["direction"] == "Поступление",
        pos=lambda o: wd.searchsorted(o["operation_date"]))
    used: set = set()
    out = []
    for e in sorted(planned, key=lambda e: (e.date, e.stream_id or "")):
        s = streams.loc[e.stream_id]
        due = pd.Timestamp(min(e.overdue_dates)) if e.overdue_dates else pd.Timestamp(e.date)
        lo = wd.searchsorted(pd.Timestamp(e.date)) - cfg.window_wd
        hi = wd.searchsorted(pd.Timestamp(e.date)) + cfg.window_wd
        cand = f[(f["key"] == str(s["counterparty_key"])) & (f["cat"] == e.category) & (f["inflow"] == (e.amount > 0))
                 & (f["pos"] >= lo) & (f["pos"] <= hi) & ~f.index.isin(used)]
        plan_abs, got, take = abs(e.amount), 0.0, []
        # у одного контрагента бывает несколько под-потоков одной категории: сначала операции, ближе всего по сумме
        cand = cand.iloc[np.argsort(np.abs(cand["amount"].to_numpy(dtype=float) - plan_abs), kind="stable")]
        for i, a in zip(cand.index, cand["amount"].to_numpy(dtype=float)):
            if got + a <= plan_abs * (1 + cfg.amount_tol):
                take.append(i)
                got += a
        if not take and len(cand):   # заплатили больше плана: одна ближайшая по сумме операция
            take, got = [cand.index[0]], float(cand["amount"].iloc[0])
        used.update(take)
        if take:
            status = "paid" if abs(got - plan_abs) <= cfg.amount_tol * plan_abs else (
                "partial" if got < plan_abs else "paid")
            last = f.loc[take, "operation_date"].max()
        else:
            status, last = "missed", as_of
        sign = 1 if e.amount > 0 else -1
        # окно ±3 р.д. ещё не закрылось к as_of: missed, но может прийти/списаться в ближайшие дни
        window_open = status == "missed" and hi < len(wd) and wd[hi] > as_of
        out.append({"date": pd.Timestamp(e.date).date().isoformat(), "category": e.category,
                    "amount_plan": round(e.amount, 2), "amount_fact": round(sign * got, 2), "status": status,
                    "days_late": _wd_between(wd, due, last), "stream_id": e.stream_id,
                    "mandatory": e.mandatory, "confidence": round(e.confidence, 2), "window_open": bool(window_open),
                    **({"overdue_from": due.date().isoformat()} if e.overdue_dates else {})})
    return out


def _wd_between(wd: pd.DatetimeIndex, a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Рабочих дней от a до b: > 0 — позже, < 0 — раньше."""
    return int(wd.searchsorted(b, side="right") - wd.searchsorted(a, side="right"))
