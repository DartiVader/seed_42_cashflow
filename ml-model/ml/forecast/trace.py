"""trace — «Как посчитано»: шаги 1–9 прогноза в цифрах (документ «Seed 42 — как всё работает», 3.1–3.9).

Только агрегаты: количества, доли, суммы по шагу, вероятности. Ни контрагентов, ни назначений, ни ИНН,
ни отдельных операций. Суммы — по счёту самой компании, их предприниматель и так видит на графике.

    [{"step": 1, "name": "Очистка", "ms": 12.3, "values": {...}}, ...]

ms — время шага в forecast(), миллисекунды. Категории (шаг 2) и регулярные платежи (шаг 3) считаются одним
проходом кода Влада, их общее время — в шаге 3, у шага 2 ms = null. Шаг 8 (сценарий) — время apply_scenario.
format_steps() — те же шаги строками для лога и экрана, без рублёвых сумм (правило логов).

Шаг 9 (план-факт) в forecast() не считается — для него отдельная ручка /plan-fact; в trace он есть
с available=false, чтобы вкладка показывала все девять шагов.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ml.pipeline.regular import CLEAN_FLAGS

STEP_NAMES = {
    1: "Очистка", 2: "Категории платежей", 3: "Регулярные платежи", 4: "Будущие события",
    5: "Модель прогноза", 6: "Монте-Карло", 7: "Кассовый разрыв", 8: "Сценарий «что если»", 9: "План-факт",
}
TOP_CATEGORIES = 8
# рублёвые значения: в JSON есть, в лог не идут
MONEY_KEYS = {"inflow_sum", "outflow_sum", "expected_net", "daily_turnover", "irregular_inflow_sum",
              "irregular_outflow_sum", "end_p10", "end_p50", "end_p90", "min_p50", "shortfall", "threshold"}


class Clock:
    """Время по шагам: lap(k) прибавляет к шагу k время с прошлого lap."""

    def __init__(self) -> None:
        self.ms: dict[int, float] = {}
        self._t = time.perf_counter()

    def lap(self, step: int) -> None:
        now = time.perf_counter()
        self.ms[step] = self.ms.get(step, 0.0) + (now - self._t) * 1000
        self._t = now


def _r(x, nd: int = 0):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def clean_step(ops: pd.DataFrame | None, hist: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    v = {"history_days": int(len(hist)),
         "gaps_in_data": int(np.sum(hist["gap_in_data"].to_numpy() & ~np.r_[False, hist["gap_in_data"].to_numpy()[:-1]])),
         "oneoff_days": int(((hist["oneoff_in"] + hist["oneoff_out"]) > 0).sum())}
    if ops is not None:
        past = ops[ops["operation_date"] <= as_of]
        v["operations"] = int(len(past))
        v.update({k.removeprefix("is_"): int(past[k].sum()) for k in CLEAN_FLAGS if k in past})
    return v


def categories_step(labels: pd.DataFrame | None, as_of_mask: pd.Series | None) -> dict:
    if labels is None:
        return {"available": False}
    cat = labels.loc[as_of_mask, "category"].dropna()
    counts = cat.value_counts()
    return {"categorized": int(len(cat)), "categories": int(counts.size),
            "unknown_share": _r((cat == "other").mean() if len(cat) else 0.0, 3),
            "top": {str(k): int(n) for k, n in counts.head(TOP_CATEGORIES).items()}}


def regular_step(streams: pd.DataFrame | None, labels: pd.DataFrame | None, as_of_mask, events) -> dict:
    if streams is None or labels is None:
        return {"available": False}
    lab = labels.loc[as_of_mask]
    st = streams if not streams.empty else pd.DataFrame(columns=["mandatory", "direction"])
    inflow = st["direction"].astype(str).str.contains("поступл")
    return {"streams": int(len(st)), "mandatory_streams": int(st["mandatory"].astype(bool).sum()),
            "inflow_streams": int(inflow.sum()),
            "regular_operations": int(lab["is_regular"].astype(bool).sum()),
            "regular_share": _r(lab["is_regular"].astype(bool).mean() if len(lab) else 0.0, 3),
            "overdue_streams": int(sum(bool(e.overdue_dates) for e in events if e.source == "regular"))}


def events_step(evs, extra, user_events) -> dict:
    amounts = np.array([e.amount for e in evs], dtype=float)
    conf = np.array([e.confidence for e in evs], dtype=float)
    return {"events": len(evs), "mandatory": int(sum(e.mandatory for e in evs)),
            "from_user": len(user_events or []), "overdue": int(sum(bool(e.overdue_dates) for e in evs)),
            "inflow_sum": _r(amounts[amounts > 0].sum()), "outflow_sum": _r(-amounts[amounts < 0].sum()),
            "expected_net": _r((amounts * conf).sum()),
            "left_to_model": len(extra)}


def model_step(model_version: str, model_name: str, in_hat, out_hat, scale: float, n_days: int) -> dict:
    return {"model_version": model_version, "model": model_name, "working_days": int(n_days),
            "daily_turnover": _r(scale), "irregular_inflow_sum": _r(np.sum(in_hat)),
            "irregular_outflow_sum": _r(np.sum(out_hat))}


def mc_step(paths: np.ndarray, future: np.ndarray, n_paths: int, seed: int, industry_pool: bool,
            pool_size: int, widen: float) -> dict:
    f = paths[:, future]
    p10, p50, p90 = np.percentile(f[:, -1], [10, 50, 90])
    return {"paths": int(n_paths), "seed": int(seed), "error_pool": "industry" if industry_pool else "all",
            "error_pool_size": int(pool_size), "widen": _r(widen, 2),
            "end_p10": _r(p10), "end_p50": _r(p50), "end_p90": _r(p90),
            "min_p50": _r(np.median(f, axis=0).min())}


def gap_step(paths: np.ndarray, future: np.ndarray, threshold: float, p_day_min: float, calibrator,
             gap, status: str) -> dict:
    below = paths[:, future] < threshold
    raw = float(below.any(axis=1).mean())
    return {"threshold": _r(threshold), "p_day_min": p_day_min, "max_p_day": _r(below.mean(axis=0).max(), 3),
            "probability_raw": _r(raw, 3),
            "probability": _r(calibrator(raw) if calibrator is not None else raw, 3),
            "calibrated": calibrator is not None, "status": status,
            "gap_date": gap.date.isoformat() if gap else None,
            "shortfall": _r(gap.shortfall) if gap else None}


def scenario_step(scenario) -> dict:
    if scenario is None:
        return {"applied": False}
    return {"applied": True, "revenue_multiplier": scenario.revenue_multiplier,
            "fixed_cost_multiplier": scenario.fixed_cost_multiplier,
            "delayed_counterparties": len(scenario.delay_counterparty),
            "extra_expenses": len(scenario.extra_expenses)}


def build(values: dict[int, dict], ms: dict[int, float] | None = None) -> list[dict]:
    values = {**values, 9: values.get(9, {"available": False, "endpoint": "/plan-fact"})}
    ms = ms or {}
    return [{"step": k, "name": STEP_NAMES[k], "ms": round(ms[k], 1) if k in ms else None, "values": values[k]}
            for k in sorted(STEP_NAMES)]


def format_steps(trace: list[dict], money: bool = False) -> list[str]:
    """Шаги строками: «Шаг 3. Регулярные платежи — 182 мс: streams=15, …». money=False — без рублёвых сумм."""
    lines = []
    for s in trace:
        t = f"{s['ms']:.0f} мс" if s.get("ms") is not None else ("время — в шаге 3" if s["step"] == 2 else "—")
        vals = []
        for k, v in s["values"].items():
            if k in MONEY_KEYS and not money:
                continue
            if isinstance(v, dict):
                v = ", ".join(f"{a} {b}" for a, b in v.items())
                vals.append(f"{k}: [{v}]")
            else:
                vals.append(f"{k}={v}")
        lines.append(f"Шаг {s['step']}. {s['name']} — {t}: " + "; ".join(vals))
    total = sum(s["ms"] for s in trace if s.get("ms") is not None)
    lines.append(f"Итого {total:.0f} мс")
    return lines
