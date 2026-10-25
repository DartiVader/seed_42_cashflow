"""Эксперимент 8.3: вероятностные события для нерегулярных клиентов и поставщиков.

Поток — контрагент × категория (revenue_client / suppliers), который код Влада не признал регулярным:
не меньше MIN_PAYMENTS платежей, обычно ≤ MAX_PER_MONTH в месяц (ежедневная торговля остаётся модели),
платежи хотя бы в MIN_MONTH_SHARE месяцев. Всё по операциям ≤ as_of.

В каждом месяце горизонта поток случается с вероятностью p = доля месяцев с платежом за последний год,
дата — равномерно в окне дней месяца [P25, P75] исторических дат платежа (не уже MIN_WINDOW дней),
сумма — бутстрэп из месячных сумм последних 6 активных месяцев. Для backtest — ожидаемое значение по дням.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.data.calendar import all_working_days

CATEGORIES = ("revenue_client", "suppliers")
MIN_PAYMENTS = 3
MAX_PER_MONTH = 2.0
MIN_MONTH_SHARE = 0.15
MIN_WINDOW = 5
LOOKBACK_DAYS = 365
AMOUNT_MONTHS = 6


@dataclass
class ProbableStream:
    key: str
    category: str
    sign: int                  # +1 поступление, −1 списание
    p_month: float
    day_lo: int
    day_hi: int
    amounts: np.ndarray        # месячные суммы для бутстрэпа


def probable_streams(ops: pd.DataFrame, labels: pd.DataFrame, as_of) -> tuple[list[ProbableStream], pd.Series]:
    """Потоки и маска их операций (индекс как у ops) — для вычитания из цели модели."""
    as_of = pd.Timestamp(as_of)
    o = ops.join(labels[["category", "is_regular"]].rename(columns={"category": "cat"}))
    o = o[(o["operation_date"] <= as_of) & o["cat"].isin(CATEGORIES) & ~o["is_regular"].astype(bool)]
    mask = pd.Series(False, index=ops.index)
    if o.empty:
        return [], mask
    inn = o["counterparty_inn"].astype("string").fillna("")
    o = o.assign(key=inn.where(inn != "", "NAME:" + o["counterparty_name"].astype("string").fillna("")),
                 month=o["operation_date"].dt.to_period("M"))
    since = as_of - pd.Timedelta(days=LOOKBACK_DAYS)
    out = []
    for (key, cat), g in o.groupby(["key", "cat"], sort=True):
        if len(g) < MIN_PAYMENTS:
            continue
        per_month = g.groupby("month")["amount"].agg(["size", "sum"])
        if per_month["size"].median() > MAX_PER_MONTH:
            continue
        first = max(g["operation_date"].min(), since)
        n_months = (as_of.to_period("M") - first.to_period("M")).n + 1
        recent = per_month[per_month.index >= since.to_period("M")]
        p = len(recent) / max(n_months, 1)
        if p < MIN_MONTH_SHARE or len(recent) == 0:
            continue
        days = g["operation_date"].dt.day
        lo, hi = int(days.quantile(0.25)), int(days.quantile(0.75))
        if hi - lo + 1 < MIN_WINDOW:
            mid = int(days.median())
            lo, hi = max(1, mid - MIN_WINDOW // 2), min(31, mid - MIN_WINDOW // 2 + MIN_WINDOW - 1)
        sign = 1 if (g["direction"] == "Поступление").all() else -1
        out.append(ProbableStream(key, cat, sign, min(p, 1.0), lo, hi,
                                  per_month["sum"].iloc[-AMOUNT_MONTHS:].to_numpy(dtype=float)))
        mask[g.index] = True
    return out, mask


def expected_daily(streams: list[ProbableStream], as_of, horizon_days: int) -> pd.DataFrame:
    """Ожидаемый поток по рабочим дням горизонта: date, amount (со знаком), category="prob_<категория>"."""
    as_of = pd.Timestamp(as_of)
    end = as_of + pd.Timedelta(days=horizon_days)
    wd = all_working_days()
    rows = []
    for s in streams:
        mean = float(s.amounts.mean()) * s.p_month * s.sign
        for m in pd.period_range(as_of.to_period("M"), end.to_period("M"), freq="M"):
            win = wd[(wd.to_period("M") == m) & (wd.day >= s.day_lo) & (wd.day <= s.day_hi)]
            if len(win) == 0:
                continue
            for d in win[(win > as_of) & (win <= end)]:
                rows.append((d, mean / len(win), f"prob_{s.category}"))
    return pd.DataFrame(rows, columns=["date", "amount", "category"])
