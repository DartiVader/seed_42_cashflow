from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.data.loaders import INFLOW
from ml.forecast.api import ForecastContext, forecast
from ml.forecast.models import ZeroFlow
from ml.forecast.montecarlo import ALL
from ml.forecast.panel import build_panel
from ml.forecast.plan_fact import plan_fact
from ml.pipeline.clean import clean_operations
from ml.pipeline.regular import MANDATORY_CATEGORIES, find_regular
from ml.tests.conftest import make_companies
from ml.tests.test_regular import RENT, company, monthly

CLIENT = dict(day=22, amount=300_000.0, direction=INFLOW, inn="0055555555", name="ООО «Клиент»",
              purpose="Оплата по счёту № 15 за поставленный товар")
AS_OF = date(2025, 10, 31)          # план — на 17.10, поступление ждём 22.10


def ctx_for(ops: pd.DataFrame, carry: bool = True) -> ForecastContext:
    ops = clean_operations(ops)
    comp = make_companies(ops)
    return ForecastContext(panel=build_panel(ops, comp), model=ZeroFlow(), pool={ALL: np.zeros((50, 23))},
                           model_version="test", ops=ops, companies=comp, event_groups=MANDATORY_CATEGORIES,
                           carry_overdue_receipts=carry)


@pytest.fixture(scope="module")
def missed_receipt():
    return company([monthly(**CLIENT, skip=("2025-10",)), monthly(**RENT)])


def test_missed_receipt_is_missed_and_carried_to_current_forecast(missed_receipt):
    ctx = ctx_for(missed_receipt)
    r = plan_fact("C001", AS_OF, context=ctx)
    assert r["as_of_plan"] == "2025-10-17"
    client = [e for e in r["events"] if e["category"] == "revenue_client"]
    assert len(client) == 1 and client[0]["status"] == "missed" and client[0]["amount_fact"] == 0
    assert client[0]["date"] == "2025-10-22" and client[0]["days_late"] == 7
    assert r["summary"]["missed_in"] == 1
    assert all(d["fact"] is not None and d["date"] > r["as_of_plan"] for d in r["daily"])

    now = forecast("C001", AS_OF, context=ctx).to_dict()
    carried = [e for e in now["events"] if e["category"] == "revenue_client" and "overdue_from" in e]
    assert len(carried) == 1 and carried[0]["overdue_from"] == "2025-10-22"
    assert carried[0]["amount"] == pytest.approx(300_000, rel=0.02) and 0 < carried[0]["confidence"] < 1
    # без флага поступление ждёт только модель: событием в прогноз не идёт
    off = forecast("C001", AS_OF, context=ctx_for(missed_receipt, carry=False)).to_dict()
    assert not [e for e in off["events"] if e["category"] == "revenue_client"]


def test_paid_receipt_is_paid():
    ops = company([monthly(**CLIENT), monthly(**RENT)])
    client = [e for e in plan_fact("C001", AS_OF, context=ctx_for(ops))["events"] if e["category"] == "revenue_client"]
    assert len(client) == 1 and client[0]["status"] == "paid" and client[0]["days_late"] == 0


def test_partial_receipt_is_partial():
    ops = company([monthly(**CLIENT), monthly(**RENT)])
    hit = (ops["counterparty_inn"] == CLIENT["inn"]) & (ops["operation_date"].dt.month == 10)
    ops.loc[hit, "amount"] = 120_000.0
    client = [e for e in plan_fact("C001", AS_OF, context=ctx_for(ops))["events"] if e["category"] == "revenue_client"]
    assert client[0]["status"] == "partial" and client[0]["amount_fact"] == pytest.approx(120_000)


def test_fact_after_as_of_does_not_change_result(missed_receipt):
    a = plan_fact("C001", AS_OF, context=ctx_for(missed_receipt))
    future = missed_receipt["operation_date"] > pd.Timestamp(AS_OF)
    changed = missed_receipt.copy()
    changed.loc[future, "amount"] *= 7
    late = changed[changed["counterparty_inn"] == CLIENT["inn"]].iloc[[-1]].assign(
        operation_date=pd.Timestamp("2025-11-05"), operation_id="late-pay")
    b = plan_fact("C001", AS_OF, context=ctx_for(pd.concat([changed, late], ignore_index=True)))
    assert a == b


def test_overdue_receipt_confidence_follows_client_history():
    as_of = date(2025, 10, 27)                       # ждали 22.10, опоздание 3 р.д.
    # клиент каждый третий месяц платит на неделю позже обычного — опоздание на 3 р.д. для него не редкость
    late = monthly(**CLIENT, end="2025-09-30")
    shift = late["operation_date"].dt.month % 3 == 0
    late.loc[shift, "operation_date"] = late.loc[shift, "operation_date"] + pd.offsets.BDay(5)
    late_ops = company([late])
    # клиент платит день в день, но два месяца пропустил совсем
    skip_ops = company([monthly(**CLIENT, end="2025-09-30", skip=("2025-04", "2025-06"))])
    conf = {}
    for name, ops in (("late", late_ops), ("skip", skip_ops)):
        ev = [e for e in find_regular(ops, as_of, 30) if e.category == "revenue_client" and e.overdue_dates]
        conf[name] = ev[0].confidence
    assert conf["late"] > 0.5 > conf["skip"]
