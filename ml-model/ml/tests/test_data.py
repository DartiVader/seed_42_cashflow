from datetime import date

import pandas as pd
import pytest

from ml.data.calendar import calendar_table, is_working_day, next_working_days
from ml.data.loaders import INFLOW, OUTFLOW
from ml.forecast.panel import build_panel
from ml.pipeline.clean import clean_operations
from ml.tests.conftest import make_companies, make_ops, rebalance


def test_calendar_holidays_and_working_saturdays():
    assert not is_working_day(date(2026, 1, 9))      # перенос с 3 января
    assert not is_working_day(date(2025, 6, 13))
    assert is_working_day(date(2025, 11, 1))         # рабочая суббота
    assert is_working_day(date(2025, 2, 24))         # в 2025 переноса 23 февраля не было
    assert list(next_working_days("2026-05-08", 1)) == [pd.Timestamp("2026-05-12")]
    cal = calendar_table().set_index("date")
    assert cal.loc["2026-05-12", "after_holiday"] == 1
    assert cal.loc["2026-05-18", "after_holiday"] == 0  # обычный понедельник


def test_gap_detected_where_balance_jumps():
    ops = make_ops(company_ids=("C001",), n_days=120)
    days = sorted(ops["operation_date"].unique())
    lost = set(days[50:60])
    ops = ops[~ops["operation_date"].isin(lost)]        # остаток не пересчитываем — как в выгрузке
    panel = build_panel(clean_operations(ops), make_companies(ops))
    flagged = set(panel.loc[panel["gap_in_data"], "date"])
    assert flagged == lost | {days[60]}


def test_duplicates_own_transfers_and_error_refunds_leave_flow_clean():
    ops = make_ops(company_ids=("C001",), n_days=80)
    d1, d2 = ops["operation_date"].iloc[40], ops["operation_date"].iloc[60]
    extra = pd.DataFrame([
        ("C001", d1, 1_000_000.0, OUTFLOW, None, "ООО «А»",
         "Перевод собственных средств на расчетный счет в АО «Банк-2». НДС не облагается"),
        ("C001", d1, 7_777.0, OUTFLOW, "0033333333", "ООО «Б»", "Оплата по счету № 5"),
        ("C001", d2, 7_777.0, INFLOW, "0033333333", "ООО «Б»",
         "Возврат платежа: неверно указаны реквизиты получателя. Оплата по счету № 5"),
    ], columns=["company_id", "operation_date", "amount", "direction",
                "counterparty_inn", "counterparty_name", "payment_purpose"])
    extra["operation_id"] = ["X1", "X2", "X3"]
    ops = rebalance(pd.concat([ops, extra], ignore_index=True))
    dup = ops.iloc[[5]].assign(operation_id="DUP")          # дубль без отражения в остатке
    ops = pd.concat([ops, dup], ignore_index=True)

    clean = clean_operations(ops)
    assert clean["is_duplicate"].sum() == 1
    assert clean["is_own_transfer"].sum() == 1
    assert clean["is_error_refund"].sum() == 2
    panel = build_panel(clean, make_companies(ops)).set_index("date")
    assert not panel["gap_in_data"].any()
    assert panel.loc[d1, "own_out"] == 1_000_000.0
    assert 1_000_000.0 > panel.loc[d1, "out_flow"]
    assert panel.loc[d2, "in_flow"] == panel.loc[d2, "all_in"] - 7_777.0


def test_founder_loan_is_rescue_not_flow():
    ops = make_ops(company_ids=("C001",), n_days=60)
    d = ops["operation_date"].iloc[30]
    loan = pd.DataFrame([("C001", d, 500_000.0, INFLOW, None, "Учредитель (физическое лицо)",
                          "Предоставление беспроцентного займа учредителем по договору № 1/26. НДС не облагается",
                          "L1")], columns=["company_id", "operation_date", "amount", "direction", "counterparty_inn",
                                           "counterparty_name", "payment_purpose", "operation_id"])
    ops = rebalance(pd.concat([ops, loan], ignore_index=True))
    clean = clean_operations(ops)
    assert clean["is_founder_financing"].sum() == 1
    panel = build_panel(clean, make_companies(ops)).set_index("date")
    assert panel.loc[d, "founder_in"] == 500_000.0
    assert panel.loc[d, "rescue_in"] == 500_000.0
    assert panel.loc[d, "in_flow"] == pytest.approx(panel.loc[d, "all_in"] - 500_000.0)
