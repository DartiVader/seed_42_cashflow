from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from ml.data.calendar import next_working_days
from ml.forecast.api import ForecastContext, forecast
from ml.forecast.contracts import CompanyClosedError, Event, Scenario
from ml.forecast.models import DowMean, ZeroFlow
from ml.forecast.montecarlo import ALL
from ml.forecast.panel import build_panel
from ml.pipeline.clean import clean_operations
from ml.tests.conftest import make_companies, make_ops, no_timing

H = 23


def context(model, pool=None):
    ops = make_ops(n_days=260)
    panel = build_panel(clean_operations(ops), make_companies(ops))
    if pool is None:
        rng = np.random.default_rng(0)
        pool = np.cumsum(rng.normal(0, 0.5, size=(200, H)), axis=1)
    return ForecastContext(panel=panel, model=model, pool={ALL: pool}, model_version="test")


def test_known_large_payment_gives_gap_on_its_date_with_its_size():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    as_of, b0 = last["date"], float(last["balance_eod"])
    day = next_working_days(as_of, 7)[-1]
    res = forecast("C001", as_of.date(), context=ctx, events=[
        Event(date=day.date(), amount=-(b0 + 250_000), category="rent", source="contract",
              confidence=1.0, mandatory=True)])
    gap = res.gaps[0]
    assert gap.date == day.date()
    assert gap.shortfall == pytest.approx(250_000, abs=1)
    assert gap.probability == 1.0
    assert any("Аренда" in r for r in gap.reasons)
    assert res.status == "gap_expected"


def test_monte_carlo_is_reproducible_and_json_matches_contract():
    ctx = context(DowMean())
    as_of = ctx.panel["date"].max().date()
    a = forecast("C002", as_of, context=ctx, seed=7).to_dict()
    b = forecast("C002", as_of, context=ctx, seed=7).to_dict()
    assert no_timing(a) == no_timing(b)
    assert set(a) == {"company_id", "as_of", "model_version", "data_quality", "status", "daily", "events", "gaps",
                      "trace"}
    assert a["status"] in ("already_negative", "gap_expected", "ok")
    assert len(a["daily"]) == 30
    assert all(d["p10"] <= d["p50"] <= d["p90"] for d in a["daily"])


def test_revenue_drop_does_not_improve_min_balance():
    ctx = context(DowMean())
    as_of = ctx.panel["date"].max().date()
    base = forecast("C001", as_of, context=ctx)
    worse = forecast("C001", as_of, context=ctx, scenario=Scenario(revenue_multiplier=0.7))
    for a, b in zip(base.daily, worse.daily):
        assert b.p50 <= a.p50 + 1e-6 and b.p10 <= a.p10 + 1e-6


def test_empty_events_and_short_history_do_not_fail():
    ctx = context(DowMean())
    first = ctx.panel[ctx.panel["company_id"] == "C003"]["date"].iloc[15]
    res = forecast("C003", first.date(), context=ctx, events=[])
    assert res.data_quality.short_history
    assert len(res.daily) == 30


def test_closed_account_gives_clear_message():
    ctx = context(DowMean())
    late = ctx.panel["date"].max() + timedelta(days=60)
    with pytest.raises(CompanyClosedError, match="нет операций"):
        forecast("C001", late.date(), context=ctx)


def test_overdraft_term_until_p50_recovers_or_end_of_forecast():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    as_of, b0 = last["date"], float(last["balance_eod"])
    days = next_working_days(as_of, 10)
    out = Event(date=days[2].date(), amount=-(b0 + 100_000), category="rent", source="contract", confidence=1.0)
    back = Event(date=days[6].date(), amount=200_000, category="revenue", source="invoice", confidence=1.0)
    gap = forecast("C001", as_of.date(), context=ctx, events=[out, back]).gaps[0]
    end = as_of + timedelta(days=30)
    assert gap.actions[-1].startswith(f"Чтобы не уйти в минус до {end:%d.%m}, нужен лимит ~100 тыс. ₽")
    assert f"(до {days[6]:%d.%m})" in gap.actions[-1]
    gap = forecast("C001", as_of.date(), context=ctx, events=[out]).gaps[0]
    assert gap.actions[-1] == f"Чтобы не уйти в минус до {end:%d.%m}, нужен лимит ~100 тыс. ₽"


def test_calibrator_is_monotone_and_applied():
    from ml.evaluation.calibration import fit_calibrator

    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 2000)
    truth = rng.uniform(0, 1, 2000) < p * 0.2          # сырая вероятность завышена в 5 раз
    cal = fit_calibrator(p, truth, "counterfactual")
    grid = np.linspace(0, 1, 11)
    assert np.all(np.diff(cal(grid)) >= 0)
    assert cal(0.9) < 0.35

    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    ctx.calibrator = cal
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    day = next_working_days(last["date"], 3)[-1]
    res = forecast("C001", last["date"].date(), context=ctx, events=[
        Event(date=day.date(), amount=-(float(last["balance_eod"]) + 1e5), category="rent", source="contract",
              confidence=1.0)])
    assert res.gaps[0].probability == pytest.approx(float(cal(1.0)))


def test_gap_is_never_before_as_of_when_statement_ends_earlier():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    as_of = last["date"] + timedelta(days=7)            # выписка закончилась за неделю до даты прогноза
    soon = next_working_days(last["date"], 2)[-1]       # платёж между концом выписки и as_of — уже прошлое
    later = next_working_days(as_of, 3)[-1]
    big = -(float(last["balance_eod"]) + 1e5)
    res = forecast("C001", as_of.date(), context=ctx, events=[
        Event(date=soon.date(), amount=big, category="rent", source="contract", confidence=1.0)])
    assert all(g.date > as_of.date() for g in res.gaps)
    res = forecast("C001", as_of.date(), context=ctx, events=[
        Event(date=later.date(), amount=big, category="rent", source="contract", confidence=1.0)])
    assert res.gaps[0].date == later.date()


def test_days_since_last_operation_in_data_quality():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    res = forecast("C001", (last["date"] + timedelta(days=5)).date(), context=ctx)
    assert res.data_quality.days_since_last_operation == 5
    assert res.to_dict()["data_quality"]["days_since_last_operation"] == 5


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "cashflow_data" / "cashflow_dataset_participants"
RESIDUALS = ROOT / "reports" / "backtest_residuals.parquet"


@pytest.fixture(scope="module")
def real_context():
    if not (DATA.exists() and RESIDUALS.exists() and (ROOT / "models" / "lgbm_net-v2").exists()):
        pytest.skip("нет реальных данных или обученной модели")
    return ForecastContext.load(DATA, ROOT / "models", RESIDUALS)


@pytest.mark.parametrize("company_id", ["C103", "C013", "C080"])
def test_daily_starts_after_as_of_when_statement_ends_earlier(real_context, company_id):
    as_of = date(2026, 9, 30)
    hist = real_context.panel[real_context.panel["company_id"] == company_id]
    last_op = hist.loc[hist["n_ops"] > 0, "date"].max().date()
    assert last_op < as_of                      # предпосылка теста: выписка кончается раньше
    res = forecast(company_id, as_of, context=real_context)
    assert real_context.model_version == "lgbm_net-v2"
    assert res.daily[0].date > as_of
    assert all(d.date > as_of for d in res.daily)
    assert all(g.date > as_of for g in res.gaps)
    assert res.data_quality.days_since_last_operation == (as_of - last_op).days


def founder_funded_context(start_balance=500_000.0):
    """C001: последние 70 рабочих дней выручки нет, расходы покрывают займы учредителя; C002 — обычная."""
    from ml.data.loaders import INFLOW
    from ml.tests.conftest import rebalance
    import pandas as pd

    ops = make_ops(company_ids=("C001", "C002"), n_days=260)
    days = sorted(ops["operation_date"].unique())
    cut = days[-70]
    ops = ops[~((ops["company_id"] == "C001") & (ops["direction"] == INFLOW) & (ops["operation_date"] >= cut))]
    loans = pd.DataFrame([("C001", d, 300_000.0, INFLOW, None, "Учредитель (физическое лицо)",
                           "Предоставление беспроцентного займа учредителем по договору № 1/26", f"L{i}")
                          for i, d in enumerate(days[-70::10])],
                         columns=["company_id", "operation_date", "amount", "direction", "counterparty_inn",
                                  "counterparty_name", "payment_purpose", "operation_id"])
    ops = rebalance(pd.concat([ops, loans], ignore_index=True), start_balance)
    panel = build_panel(clean_operations(ops), make_companies(ops))
    return ForecastContext(panel=panel, model=ZeroFlow(), pool={ALL: np.zeros((50, H))}, model_version="test")


def _big_payment(ctx, cid):
    last = ctx.panel[ctx.panel["company_id"] == cid].iloc[-1]
    day = next_working_days(last["date"], 3)[-1]
    return last["date"].date(), [Event(date=day.date(), amount=-(abs(float(last["balance_eod"])) + 1e6),
                                       category="rent", source="contract", confidence=1.0, mandatory=True)]


def test_founder_funded_company_gets_funding_reason_first():
    ctx = founder_funded_context()
    as_of, events = _big_payment(ctx, "C001")
    res = forecast("C001", as_of, context=ctx, events=events)
    reasons = res.gaps[0].reasons
    hist = ctx.panel[ctx.panel["company_id"] == "C001"]
    last_rev = hist.loc[hist["y_in"] > 0, "date"].max()
    months = round((as_of - last_rev.date()).days / 30.4)
    assert reasons[0].startswith("С ")
    assert reasons[1].startswith(f"Выручки нет {months} мес., расходы последние месяцы покрывались "
                                 "деньгами учредителя (~")
    assert "млн ₽/мес." in reasons[1] or "тыс. ₽/мес." in reasons[1]
    assert "(без новых взносов учредителя)" in res.gaps[0].actions[-1]
    assert any("Аренда" in r for r in reasons)
    # у компании с выручкой такой причины нет
    as_of, events = _big_payment(ctx, "C002")
    gap = forecast("C002", as_of, context=ctx, events=events).gaps[0]
    assert not any("учредител" in r for r in gap.reasons + gap.actions)


def test_funding_reason_goes_after_overdraft():
    ctx = founder_funded_context(start_balance=-30_000_000.0)
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    assert last["balance_eod"] < 0
    reasons = forecast("C001", last["date"].date(), context=ctx).gaps[0].reasons
    assert reasons[0].startswith("Счёт уже в овердрафте")
    assert reasons[1].startswith("С ")
    assert reasons[2].startswith("Выручки нет")


def test_shortfall_at_gap_matches_single_large_payment():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    as_of, b0 = last["date"], float(last["balance_eod"])
    day = next_working_days(as_of, 7)[-1]
    gap = forecast("C001", as_of.date(), context=ctx, events=[
        Event(date=day.date(), amount=-(b0 + 250_000), category="rent", source="contract", confidence=1.0)]).gaps[0]
    assert gap.shortfall_at_gap == pytest.approx(250_000, rel=0.05)
    end = next_working_days(day, 4)[-1]                     # окно 5 рабочих дней с даты разрыва
    assert gap.reasons[0] == f"С {day:%d.%m} по {end:%d.%m} не хватит ~250 тыс. ₽"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_shortfall_amounts_are_ordered(seed):
    from ml.forecast.gaps import shortfall_stats

    ctx = context(DowMean())      # шумный пул: траектории расходятся
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    day = next_working_days(last["date"], 4)[-1]
    gap = forecast("C001", last["date"].date(), context=ctx, seed=seed, events=[
        Event(date=day.date(), amount=-(float(last["balance_eod"]) + 300_000), category="rent", source="contract",
              confidence=1.0)]).gaps[0]
    assert gap.shortfall_at_gap_low <= gap.shortfall_at_gap <= gap.shortfall_at_gap_high
    assert gap.shortfall_low <= gap.shortfall <= gap.shortfall_high
    assert gap.shortfall_at_gap <= gap.shortfall
    d = forecast("C001", last["date"].date(), context=ctx, seed=seed).to_dict()   # без разрыва полей нет
    assert all("shortfall_at_gap" in g for g in d["gaps"])

    rng = np.random.default_rng(seed)
    paths = np.cumsum(rng.normal(-1, 3, size=(500, 20)), axis=1)
    sf = shortfall_stats(paths, 3, 0.0, 5)
    for kind in ("at_gap", "total"):
        m, p10, p90, p25, p75 = sf[kind]
        assert p10 <= p25 <= m <= p75 <= p90


# --------------------------------------------------------------- 3a: выписка из запроса

def test_statement_from_request_matches_dataset(real_context):
    from ml.data.loaders import load_operations
    ops = load_operations(DATA / "statements" / "C140.csv")
    a = forecast("C140", date(2026, 9, 30), context=real_context).to_dict()
    b = forecast("C140", date(2026, 9, 30), context=real_context, ops=ops).to_dict()
    assert no_timing(a) == no_timing(b)


def test_unknown_company_with_and_without_industry(real_context):
    from ml.data.loaders import load_operations
    ops = load_operations(DATA / "statements" / "C140.csv").drop(columns="company_id")
    r = forecast("NEW1", date(2026, 9, 30), context=real_context, ops=ops)
    assert r.data_quality.industry_known is False
    assert r.to_dict()["data_quality"]["industry_known"] is False
    r = forecast("NEW1", date(2026, 9, 30), context=real_context, ops=ops, industry="Общепит (кофейня, кафе)")
    assert r.data_quality.industry_known is None and "industry_known" not in r.to_dict()["data_quality"]


@pytest.mark.parametrize("break_it, message", [
    (lambda o: o.drop(columns="balance_eod"), "не хватает колонок: balance_eod"),
    (lambda o: o.assign(counterparty_inn=1234567890), "ИНН контрагента должен быть строкой"),
    (lambda o: o.assign(operation_date="вчера"), "Не удалось прочитать дату"),
    (lambda o: o.assign(amount=-o["amount"]), "больше нуля"),
    (lambda o: o.assign(direction="Приход"), "Направление операции"),
    (lambda o: o.assign(company_id="C999"), "другой компании"),
])
def test_invalid_statement_gives_clear_error(break_it, message):
    from ml.forecast.contracts import InvalidStatementError
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    ops = make_ops(company_ids=("C001",), n_days=120)
    with pytest.raises(InvalidStatementError, match=message):
        forecast("C001", ops["operation_date"].max().date(), context=ctx, ops=break_it(ops))


def test_statement_future_operations_are_cut():
    ctx = context(ZeroFlow(), pool=np.zeros((50, H)))
    ops = make_ops(company_ids=("C001",), n_days=120)
    as_of = ops["operation_date"].iloc[len(ops) // 2]
    a = forecast("C001", as_of.date(), context=ctx, ops=ops[ops["operation_date"] <= as_of])
    b = forecast("C001", as_of.date(), context=ctx, ops=ops)
    assert no_timing(a.to_dict()) == no_timing(b.to_dict())


# --------------------------------------------------------------- 3: советы с пересчётом

def _advice_case(extra_events, model=None):
    ctx = context(model or ZeroFlow(), pool=np.zeros((50, H)))
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    days = next_working_days(last["date"], 12)
    b0 = float(last["balance_eod"])
    return ctx, last["date"].date(), days, b0, extra_events(days, b0)


def test_postpone_of_single_optional_payment_removes_gap():
    ctx, as_of, days, b0, evs = _advice_case(lambda d, b0: [
        Event(date=d[2].date(), amount=-(b0 + 50_000), category="marketing", source="contract", confidence=1.0),
        Event(date=d[5].date(), amount=200_000, category="revenue_client", source="invoice", confidence=1.0),
        Event(date=d[1].date(), amount=-10_000, category="rent", source="contract", confidence=1.0, mandatory=True)])
    gap = forecast("C001", as_of, context=ctx, events=evs).gaps[0]
    det = {d["type"]: d for d in gap.actions_detail}
    assert det["postpone"]["category"] == "marketing" and det["postpone"]["prob_after"] < 0.1
    assert det["postpone"]["gap_date_after"] is None
    assert gap.actions[0].startswith("Перенесите платёж «Реклама»") and "не будет (риск 100% → 0%)" in gap.actions[0]
    assert gap.actions_detail[-1]["type"] == "overdraft" and gap.actions[-1].startswith("Чтобы не уйти в минус")


def test_mandatory_payments_are_never_moved():
    ctx, as_of, days, b0, evs = _advice_case(lambda d, b0: [
        Event(date=d[2].date(), amount=-(b0 + 50_000), category="rent", source="contract", confidence=1.0,
              mandatory=True),
        Event(date=d[3].date(), amount=-(b0 + 50_000), category="suppliers", source="contract", confidence=1.0,
              mandatory=True),
        Event(date=d[3].date(), amount=-(b0 + 50_000), category="tax_enp", source="tax", confidence=1.0),
        Event(date=d[6].date(), amount=500_000, category="revenue_client", source="invoice", confidence=1.0)])
    for gap in forecast("C001", as_of, context=ctx, events=evs).gaps:
        moved = [d for d in gap.actions_detail if d["type"] in ("postpone", "negotiate_supplier")]
        assert moved == []


def test_advice_without_effect_is_dropped_and_recalc_is_deterministic():
    ctx, as_of, days, b0, evs = _advice_case(lambda d, b0: [
        Event(date=d[2].date(), amount=-(b0 + 500_000), category="rent", source="contract", confidence=1.0,
              mandatory=True),
        Event(date=d[3].date(), amount=-1_000, category="marketing", source="contract", confidence=1.0)])
    gap = forecast("C001", as_of, context=ctx, events=evs).gaps[0]
    assert [d["type"] for d in gap.actions_detail] == ["overdraft"]      # перенос 1 тыс. разрыв не трогает

    ctx = context(DowMean())                                               # шумный пул и поток
    last = ctx.panel[ctx.panel["company_id"] == "C001"].iloc[-1]
    d = next_working_days(last["date"], 8)
    evs = [Event(date=d[3].date(), amount=-(float(last["balance_eod"]) + 300_000), category="marketing",
                 source="contract", confidence=0.9)]
    a = forecast("C001", last["date"].date(), context=ctx, events=evs, seed=7).gaps[0].actions_detail
    b = forecast("C001", last["date"].date(), context=ctx, events=evs, seed=7).gaps[0].actions_detail
    assert a == b and any(x["type"] == "postpone" for x in a)


@pytest.mark.parametrize("company_id", ["C044", "C140", "C103"])
def test_forecast_with_advice_is_fast(real_context, company_id):
    import time
    forecast(company_id, date(2026, 9, 30), context=real_context)          # прогрев
    t = time.perf_counter()
    r = forecast(company_id, date(2026, 9, 30), context=real_context)
    assert time.perf_counter() - t <= 1.5
    assert r.gaps and r.gaps[0].actions_detail[-1]["type"] == "overdraft"
