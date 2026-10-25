import json

import pytest

from ml.forecast.api import forecast
from ml.forecast.contracts import Scenario
from ml.tests.test_plan_fact import AS_OF, CLIENT, ctx_for
from ml.tests.test_regular import RENT, company, monthly


@pytest.fixture(scope="module")
def result():
    ops = company([monthly(**CLIENT), monthly(**RENT)])
    return forecast("C001", AS_OF, context=ctx_for(ops), scenario=Scenario(revenue_multiplier=0.8)), ops


def test_trace_has_nine_steps_in_numbers(result):
    r, _ = result
    steps = r.to_dict()["trace"]
    assert [s["step"] for s in steps] == list(range(1, 10))
    v = {s["step"]: s["values"] for s in steps}
    assert v[1]["operations"] > 0 and v[2]["categorized"] > 0
    assert v[3]["streams"] >= 2 and v[3]["mandatory_streams"] >= 1          # аренда — обязательный поток
    assert v[4]["events"] == len(r.events)
    assert v[6]["paths"] == 1000 and v[6]["end_p10"] <= v[6]["end_p50"] <= v[6]["end_p90"]
    assert 0 <= v[7]["probability_raw"] <= 1 and v[7]["status"] == r.status
    assert v[8]["applied"] and v[8]["revenue_multiplier"] == 0.8
    assert v[9] == {"available": False, "endpoint": "/plan-fact"}


def test_trace_has_no_counterparty_data(result):
    r, ops = result
    text = json.dumps(r.to_dict()["trace"], ensure_ascii=False)
    for col in ("counterparty_inn", "counterparty_name", "payment_purpose"):
        for value in ops[col].dropna().unique():
            assert str(value) not in text
