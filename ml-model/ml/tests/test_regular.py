from datetime import date

import pandas as pd
import pytest

from ml.data.calendar import is_working_day, working_days
from ml.data.loaders import INFLOW, OUTFLOW
from ml.forecast.contracts import Event
from ml.pipeline.regular import find_regular, label_operations, merge_events
from ml.tests.conftest import make_ops, rebalance

COLS = ["company_id", "operation_date", "amount", "direction", "counterparty_inn", "counterparty_name",
        "payment_purpose", "operation_id"]


def monthly(day: int, amount: float, direction: str, inn: str | None, name: str, purpose: str,
            start="2025-01-09", end="2025-11-30", skip=()) -> pd.DataFrame:
    """Платёж раз в месяц в первый рабочий день ≥ day."""
    wd = working_days(start, end)
    rows = []
    for m in pd.period_range(start, end, freq="M"):
        if str(m) in skip:
            continue
        cand = wd[(wd.to_period("M") == m) & (wd.day >= day)]
        if len(cand):
            rows.append(("C001", cand[0], amount, direction, inn, name, purpose, f"{name[:3]}-{m}"))
    return pd.DataFrame(rows, columns=COLS)


def company(extra: list[pd.DataFrame]) -> pd.DataFrame:
    ops = make_ops(company_ids=("C001",), n_days=230)
    ops = ops[ops["payment_purpose"] != "Заработная плата"]
    return rebalance(pd.concat([ops, *extra], ignore_index=True))


RENT = dict(day=5, amount=150_000.0, direction=OUTFLOW, inn="0033333333", name="ООО «Арендодатель»",
            purpose="Оплата аренды нежилого помещения по договору № 7")
SALARY = dict(day=10, amount=90_000.0, direction=OUTFLOW, inn=None, name="Сотрудники",
              purpose="Перечисление заработной платы за месяц")
AS_OF = date(2025, 10, 31)


def test_regular_does_not_see_future():
    base = company([monthly(**RENT), monthly(**SALARY)])
    future = base[base["operation_date"] > pd.Timestamp(AS_OF)].index
    changed = base.copy()
    changed.loc[future, "amount"] *= 7
    changed = pd.concat([changed, monthly(**{**RENT, "inn": "0044444444", "name": "ООО «Новый»"},
                                          start="2025-11-01", end="2025-11-30")], ignore_index=True)
    a = label_operations(base, AS_OF)
    b = label_operations(changed, AS_OF).loc[a.index]
    past = a["operation_date"] <= pd.Timestamp(AS_OF)
    cols = ["category", "mandatory", "is_regular", "stream_id"]
    pd.testing.assert_frame_equal(a.loc[past, cols], b.loc[past, cols])
    assert a.loc[~past, "category"].isna().all() and not a.loc[~past, "is_regular"].any()
    assert find_regular(base, AS_OF, 30) == find_regular(changed, AS_OF, 30)


def test_events_only_on_working_days_after_as_of():
    # аренда 1-го: январь и май — праздники, платёж должен уйти на рабочий день
    ops = company([monthly(**{**RENT, "day": 1}, start="2025-01-09", end="2026-04-30")])
    as_of = date(2026, 4, 28)
    events = find_regular(ops, as_of, 60)
    rent = [e for e in events if e.category == "rent"]
    assert rent and all(is_working_day(e.date) and e.date > as_of for e in events)
    assert rent[0].date == date(2026, 5, 4)          # 1–3 мая праздники и выходные
    assert rent[0].stream_id == "0033333333|rent|out" and rent[0].mandatory and rent[0].source == "regular"


def test_credit_tranche_and_founder_money_are_never_regular():
    tranche = monthly(day=15, amount=500_000.0, direction=INFLOW, inn="0055555555", name="ПАО «Банк»",
                      purpose="Выдача кредита (транш) по договору кредитной линии № КЛ-1")
    founder = monthly(day=20, amount=300_000.0, direction=INFLOW, inn=None, name="Учредитель (физическое лицо)",
                      purpose="Предоставление беспроцентного займа по договору № 1/25")
    ops = company([tranche, founder, monthly(**RENT)])
    lab = label_operations(ops, AS_OF)
    lab = lab[lab["operation_date"] <= pd.Timestamp(AS_OF)]
    is_tranche = lab["payment_purpose"].str.contains("транш")
    is_founder = lab["counterparty_name"].str.contains("Учредитель")
    assert lab.loc[is_tranche, "category"].eq("loan_received").all()
    assert lab.loc[is_founder, "category"].eq("owner_injection").all()
    assert not lab.loc[is_tranche | is_founder, "is_regular"].any()
    assert lab.loc[lab["payment_purpose"].str.contains("аренды"), "is_regular"].all()
    assert {e.category for e in find_regular(ops, AS_OF, 30)} & {"loan_received", "owner_injection"} == set()


def test_overdue_salary_is_carried_forward_and_summed():
    ops = company([monthly(**SALARY, skip=("2025-09", "2025-10"))])
    events = [e for e in find_regular(ops, AS_OF, 30) if e.category.startswith("salary")]
    overdue = [e for e in events if e.overdue_dates]
    assert len(overdue) == 1
    e = overdue[0]
    assert e.date == date(2025, 11, 1)               # 01.11.2025 — рабочая суббота (перенос)
    assert e.amount == pytest.approx(-180_000, rel=0.02)
    assert e.confidence == 1.0 and e.mandatory
    assert [d.month for d in e.overdue_dates] == [9, 10]
    assert all(is_working_day(d) for d in e.overdue_dates)


def test_user_event_with_same_stream_replaces_found():
    ops = company([monthly(**RENT, end="2026-02-28")])
    found = find_regular(ops, date(2025, 12, 31), 60)
    rent = [e for e in found if e.category == "rent"]
    assert len(rent) == 2                              # январь и февраль
    manual = Event(date=rent[0].date, amount=-170_000, category="rent", source="contract", confidence=1.0,
                   mandatory=True, stream_id=rent[0].stream_id)
    merged = [e for e in merge_events(found, [manual]) if e.category == "rent"]
    assert merged == [manual]                          # заменяет с даты события, не добавляется
    later = Event(date=rent[1].date, amount=-170_000, category="rent", source="manual", confidence=1.0,
                  mandatory=True, stream_id=rent[1].stream_id)
    merged = [e for e in merge_events(found, [later]) if e.category == "rent"]
    assert merged == [rent[0], later]                  # до даты события найденное остаётся


def test_short_history_without_streams_does_not_fail():
    ops = make_ops(company_ids=("C001",), n_days=12)
    as_of = ops["operation_date"].max().date()
    assert find_regular(ops, as_of, 30) == []
    lab = label_operations(ops, as_of)
    assert len(lab) == len(ops) and not lab["is_regular"].any()


def test_silent_statement_halves_confidence():
    ops = company([monthly(**RENT, end="2025-08-31")])
    ops = ops[ops["operation_date"] <= pd.Timestamp("2025-08-29")]     # выписка кончилась 29.08
    fresh = {e.stream_id: e.confidence for e in find_regular(ops, date(2025, 9, 3), 45)}
    silent = {e.stream_id: e.confidence for e in find_regular(ops, date(2025, 10, 10), 45)}
    sid = "0033333333|rent|out"
    assert fresh[sid] > 0 and silent[sid] == pytest.approx(fresh[sid] * 0.5)


def test_loan_amount_is_median_not_pulled_by_prepayment():
    loan = monthly(day=3, amount=120_000.0, direction=OUTFLOW, inn="0066666666", name="ПАО «Банк-кредитор»",
                   purpose="Погашение кредита по договору № 5")
    prepay = pd.DataFrame([("C001", pd.Timestamp("2025-06-16"), 4_000_000.0, OUTFLOW, "0066666666",
                            "ПАО «Банк-кредитор»", "Погашение кредита по договору № 5 (досрочно)", "PRE-1")],
                          columns=COLS)
    ops = company([loan, prepay])
    ev = [e for e in find_regular(ops, AS_OF, 30) if e.category == "loan_repayment"]
    assert len(ev) == 1 and ev[0].amount == pytest.approx(-120_000, rel=0.01)


def test_empty_inn_joins_stream_with_same_name():
    rent = monthly(**RENT)
    rent.loc[rent.index[[2, 6]], "counterparty_inn"] = None      # в двух месяцах ИНН не заполнен
    lab = label_operations(company([rent]), AS_OF)
    r = lab[lab["payment_purpose"].str.contains("аренды") & (lab["operation_date"] <= pd.Timestamp(AS_OF))]
    assert r["is_regular"].all() and r["stream_id"].nunique() == 1
    assert r["stream_id"].iloc[0] == "0033333333|rent|out"


@pytest.mark.parametrize("n_payments, regular", [(3, False), (4, True)])
def test_quarterly_needs_four_payments_in_a_row(n_payments, regular):
    months = ["2025-01", "2025-04", "2025-07", "2025-10"][-n_payments:]
    q = monthly(day=20, amount=50_000.0, direction=OUTFLOW, inn="0077777777", name="ООО «Аудитор»",
                purpose="Оплата услуг по договору № 3 за квартал")
    q = q[q["operation_id"].str.slice(4).isin(months)]
    lab = label_operations(company([q]), AS_OF)
    assert bool(lab.loc[lab["counterparty_name"] == "ООО «Аудитор»", "is_regular"].all()) is regular


def test_probable_streams_use_only_past_and_skip_frequent():
    from ml.pipeline.probable import expected_daily, probable_streams
    client = monthly(day=12, amount=300_000.0, direction=INFLOW, inn="0088888888", name="ООО «Клиент»",
                     purpose="Оплата по договору № 9 за услуги", skip=("2025-02", "2025-03", "2025-06", "2025-07", "2025-08"))
    ops = company([client])                                   # поставщик make_ops платит каждые 5 р.д. — частый
    lab = label_operations(ops, AS_OF)
    streams, mask = probable_streams(ops, lab, AS_OF)
    keys = {s.key for s in streams}
    assert "0088888888" in keys and "0022222222" not in keys
    s = next(s for s in streams if s.key == "0088888888")
    assert s.sign == 1 and s.p_month == pytest.approx(5 / 10)    # янв–окт 2025, платежи в 5 месяцах с интервалами 3-1-4-1
    assert mask[ops["counterparty_inn"] == "0088888888"].loc[lambda m: ops.loc[m.index, "operation_date"] <= pd.Timestamp(AS_OF)].all()
    ex = expected_daily(streams, AS_OF, 30)
    assert (pd.to_datetime(ex["date"]) > pd.Timestamp(AS_OF)).all()
    assert all(is_working_day(d.date()) for d in pd.to_datetime(ex["date"]))

    changed = ops.copy()
    future = changed["operation_date"] > pd.Timestamp(AS_OF)
    changed.loc[future, "amount"] *= 9
    s2, m2 = probable_streams(changed, label_operations(changed, AS_OF), AS_OF)
    pd.testing.assert_frame_equal(ex, expected_daily(s2, AS_OF, 30))
    assert m2.equals(mask)
