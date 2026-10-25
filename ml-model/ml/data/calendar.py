"""Производственный календарь РФ: рабочие дни и календарные признаки дня."""
from __future__ import annotations

from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

CAL_START = date(2024, 1, 1)
CAL_END = date(2027, 1, 31)


def _days(year: int, month: int, first: int, last: int) -> list[date]:
    return [date(year, month, d) for d in range(first, last + 1)]


# Нерабочие праздничные дни с учётом переносов. 2024-10 … 2026-09 сверены с данными:
# в выписках нет ни одной операции ровно в эти будни. Январь 2027 — предварительно.
HOLIDAYS = frozenset([
    *_days(2024, 1, 1, 8), date(2024, 2, 23), date(2024, 3, 8), date(2024, 4, 29),
    date(2024, 4, 30), date(2024, 5, 1), date(2024, 5, 9), date(2024, 5, 10),
    date(2024, 6, 12), date(2024, 11, 4), date(2024, 12, 30), date(2024, 12, 31),
    *_days(2025, 1, 1, 8), date(2025, 5, 1), date(2025, 5, 2), date(2025, 5, 8),
    date(2025, 5, 9), date(2025, 6, 12), date(2025, 6, 13), date(2025, 11, 3),
    date(2025, 11, 4), date(2025, 12, 31),
    *_days(2026, 1, 1, 9), date(2026, 2, 23), date(2026, 3, 9), date(2026, 5, 1),
    date(2026, 5, 11), date(2026, 6, 12), date(2026, 11, 4), date(2026, 12, 31),
    *_days(2027, 1, 1, 8),
])

# Рабочие субботы (переносы)
WORKING_WEEKENDS = frozenset([
    date(2024, 4, 27), date(2024, 11, 2), date(2024, 12, 28), date(2025, 11, 1),
])

CALENDAR_FEATURES = [
    "dow", "day_of_month", "month", "days_to_month_end",
    "days_since_prev_wd", "days_to_next_wd", "after_holiday", "pre_holiday",
]


def is_working_day(d: date) -> bool:
    if d in WORKING_WEEKENDS:
        return True
    return d.weekday() < 5 and d not in HOLIDAYS


@lru_cache(maxsize=1)
def all_working_days() -> pd.DatetimeIndex:
    days = pd.date_range(CAL_START, CAL_END, freq="D")
    return pd.DatetimeIndex([d for d in days if is_working_day(d.date())])


def working_days(start, end) -> pd.DatetimeIndex:
    """Рабочие дни в отрезке [start, end]."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.date() < CAL_START or end.date() > CAL_END:
        raise ValueError(f"календарь задан только на {CAL_START}..{CAL_END}")
    wd = all_working_days()
    return wd[(wd >= start) & (wd <= end)]


def wd_position(dates) -> np.ndarray:
    """Номер рабочего дня в глобальном календаре. Нерабочий день — ошибка."""
    pos = all_working_days().get_indexer(pd.DatetimeIndex(dates))
    if (pos < 0).any():
        raise ValueError("в списке есть нерабочие дни или даты вне календаря")
    return pos


def last_working_day(d) -> pd.Timestamp:
    """Последний рабочий день ≤ d."""
    wd = all_working_days()
    i = wd.searchsorted(pd.Timestamp(d), side="right") - 1
    if i < 0:
        raise ValueError(f"дата {d} раньше начала календаря")
    return wd[i]


def to_last_working_days(dates) -> pd.DatetimeIndex:
    """Векторный last_working_day."""
    wd = all_working_days()
    i = wd.searchsorted(pd.DatetimeIndex(dates), side="right") - 1
    if (i < 0).any():
        raise ValueError("есть даты раньше начала календаря")
    return wd[i]


def next_working_days(as_of, n: int) -> pd.DatetimeIndex:
    """n рабочих дней строго после as_of."""
    wd = all_working_days()
    i = wd.searchsorted(pd.Timestamp(as_of), side="right")
    if i + n > len(wd):
        raise ValueError("горизонт выходит за конец календаря")
    return wd[i:i + n]


def week_end_working_days() -> pd.DatetimeIndex:
    """Последний рабочий день каждой ISO-недели — даты недельных as_of."""
    wd = all_working_days().to_series()
    iso = wd.index.isocalendar()
    return pd.DatetimeIndex(wd.groupby([iso.year, iso.week]).max().sort_values().to_numpy())


@lru_cache(maxsize=1)
def calendar_table() -> pd.DataFrame:
    """Календарные признаки для каждого рабочего дня; строка i = рабочий день номер i."""
    wd = all_working_days()
    prev = wd.to_series().shift(1).fillna(wd[0] - pd.Timedelta(days=1))
    nxt = wd.to_series().shift(-1).fillna(wd[-1] + pd.Timedelta(days=1))
    dow = wd.day_of_week.to_numpy()
    since = (wd - pd.DatetimeIndex(prev)).days.to_numpy()
    until = (pd.DatetimeIndex(nxt) - wd).days.to_numpy()
    # обычные выходные (пт→пн) праздником не считаем
    after = (since > 1) & ~((dow == 0) & (since == 3))
    before = (until > 1) & ~((dow == 4) & (until == 3))
    return pd.DataFrame({
        "date": wd,
        "dow": dow,
        "day_of_month": wd.day.to_numpy(),
        "month": wd.month.to_numpy(),
        "days_to_month_end": (wd + pd.offsets.MonthEnd(0) - wd).days.to_numpy(),
        "days_since_prev_wd": since,
        "days_to_next_wd": until,
        "after_holiday": after.astype(np.int8),
        "pre_holiday": before.astype(np.int8),
    })
