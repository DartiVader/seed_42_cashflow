from datetime import date

import pandas as pd
import pytest

from ml.data.calendar import all_working_days
from ml.pipeline.clean import clean_operations
from ml.pipeline.regular import analyze, to_events
from ml.pipeline.restore import deferred_payments, restore_ops, restored_analysis
from ml.tests.test_regular import RENT, company, monthly

AS_OF = date(2025, 11, 28)
LATE_MONTHS = ("2025-06", "2025-08", "2025-09", "2025-10")   # аренда 5-го уплачена на 6 р.д. позже


def rent_company(low_balance: bool) -> pd.DataFrame:
    rent = monthly(**RENT)
    wd = all_working_days()
    late = rent["operation_date"].dt.to_period("M").astype(str).isin(LATE_MONTHS)
    rent.loc[late, "operation_date"] = [wd[wd.searchsorted(d) + 6] for d in rent.loc[late, "operation_date"]]
    ops = clean_operations(company([rent]))
    ops["balance_eod"] = 2_000_000.0
    if low_balance:   # денег на аренду нет с нормальной даты до дня оплаты
        for d in rent.loc[late, "operation_date"]:
            gap = (ops["operation_date"] >= wd[wd.searchsorted(d) - 6]) & (ops["operation_date"] < d)
            ops.loc[gap, "balance_eod"] = 40_000.0
    return ops


def rent_deferrals(ops: pd.DataFrame, as_of=AS_OF) -> pd.DataFrame:
    d = deferred_payments(ops, as_of)
    return d[d["category"] == "rent"]


def test_late_payment_without_money_is_deferred():
    d = rent_deferrals(rent_company(low_balance=True))
    assert sorted(d["operation_date"].dt.to_period("M").astype(str)) == list(LATE_MONTHS)
    assert (d["late_wd"] == 6).all()
    assert (pd.to_datetime(d["normal_date"]).dt.day.between(5, 8)).all()   # 5-е или следующий рабочий день


def test_late_payment_with_money_is_not_deferred():
    assert rent_deferrals(rent_company(low_balance=False)).empty


def test_restore_moves_only_deferred_and_keeps_amounts():
    ops = rent_company(low_balance=True)
    restored, d = restore_ops(ops, AS_OF)
    moved = restored["operation_date"] != ops["operation_date"]
    assert set(ops.index[moved]) == set(d.index)
    assert (restored.loc[moved, "operation_date"] < ops.loc[moved, "operation_date"]).all()
    pd.testing.assert_series_equal(restored["amount"], ops["amount"])


def test_restore_does_not_see_future():
    ops = rent_company(low_balance=True)
    early = date(2025, 10, 10)          # октябрьская аренда уплачена 14.10 — после этой даты
    d = rent_deferrals(ops, early)
    assert "2025-10" not in set(d["operation_date"].dt.to_period("M").astype(str))
    changed = ops.copy()
    future = changed["operation_date"] > pd.Timestamp(early)
    changed.loc[future, "balance_eod"] = 1.0
    changed.loc[future, "amount"] *= 3
    pd.testing.assert_frame_equal(d, rent_deferrals(changed, early))


def test_restored_events_are_not_later():
    ops = rent_company(low_balance=True)
    ra = analyze(ops, AS_OF, 45)
    rent = lambda ev: [e.date for e in ev if e.category == "rent"]
    orig, rest = rent(to_events(ra, 45)), rent(to_events(restored_analysis(ops, AS_OF, ra, 45), 45))
    assert orig and rest and rest[0] < orig[0]       # 10.12 → 08.12
    assert restored_analysis(ops, AS_OF, ra, 45).labels.equals(ra.labels)   # разметка не меняется
