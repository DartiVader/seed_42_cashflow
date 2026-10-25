"""Регулярные платежи → будущие события. Тонкая обёртка над кодом Влада (ml/pipeline/vlad).

    label_operations(ops, as_of)            те же строки + category, category_name, mandatory, is_regular, stream_id
    find_regular(ops, as_of, horizon_days)  события в горизонте (после as_of), у каждого stream_id
    is_regular(ops, as_of)                  = label_operations(...)["is_regular"]

Поверх кода Влада:
- в analyze_payments идёт только операционный поток: дубли, переводы своих средств, деньги учредителя
  и ошибочные платежи с возвратами помечены в clean_operations и регулярными не бывают никогда;
- рабочие дни — ml.data.calendar;
- просроченные платежи не пропадают: обязательный — одним событием на ближайший рабочий день после
  as_of с уверенностью 1,0 (пропущенные периоды складываются), поступление — с уверенностью по истории
  задержек этого контрагента (overdue_receipt_confidence);
- поток, где обычно больше одного платежа в месяц и Влад не разбил его на под-потоки, — не регулярный;
- выписка молчит больше 20 рабочих дней до as_of — уверенность всех регулярных событий × 0,5;
- confidence события — вероятность, что платёж будет: регулярность месяцев потока (gap_conf у Влада).
  Общий confidence Влада учитывает и разброс суммы: у ЕНП он бывает 0, а налог при этом платится.
"""
from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

from ml.data.calendar import all_working_days, is_working_day
from ml.forecast.contracts import Event
from ml.pipeline.clean import clean_operations

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from ml.pipeline.vlad import analyze_payments as vlad
    from ml.pipeline.vlad.payment_categories import CATEGORIES

# никогда не регулярные: финансирование, служебные и неопознанные операции
NEVER_REGULAR = {"loan_received", "owner_injection", "owner_withdrawal", "own_transfer", "refund", "other"}
MANDATORY_CATEGORIES = frozenset(vlad.MANDATORY_CATEGORIES)
TAX = frozenset({"tax_enp", "tax_other"})
SALARY = frozenset({"salary", "salary_advance", "salary_settlement"})
REVENUE = frozenset(c for c, v in CATEGORIES.items() if v[0] == "revenue")
CLEAN_FLAGS = ("is_duplicate", "is_own_transfer", "is_founder_financing", "is_error_refund")
LABEL_COLUMNS = ["category", "category_name", "mandatory", "is_regular", "stream_id"]


@dataclass(frozen=True)
class RegularConfig:
    overdue_inflow_prior: float = 0.5    # просроченное поступление без истории задержек и пропусков
    overdue_inflow_min: float = 0.05
    overdue_inflow_max: float = 0.95
    stale_after_wd: int = 20             # выписка молчит дольше (рабочих дней до as_of) —
    stale_factor: float = 0.5            # уверенность всех регулярных событий × 0,5


def _business_day(d) -> bool:
    return is_working_day(pd.Timestamp(d).date())


VLAD_CONFIG = {"business_day_calendar": _business_day}


def next_working_day(d) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize() + pd.Timedelta(days=1)
    while not _business_day(d):
        d += pd.Timedelta(days=1)
    return d


@dataclass
class RegularAnalysis:
    labels: pd.DataFrame       # индекс как у ops, колонки LABEL_COLUMNS
    streams: pd.DataFrame      # потоки Влада на as_of
    prognosis: pd.DataFrame    # экземпляры потоков в горизонте (по Владу)
    as_of: pd.Timestamp
    silent_wd: int = 0         # рабочих дней после последней операции до as_of включительно
    # stream_id, operation_date — регулярные операции ≤ as_of (история задержек просроченных поступлений)
    payments: pd.DataFrame = field(default_factory=pd.DataFrame)
    # ключ контрагента Влада (ИНН или NAME:имя) для операций ≤ as_of — сверка план-факт; не логировать
    counterparty_key: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))


def analyze(ops: pd.DataFrame, as_of: date, horizon_days: int = 30) -> RegularAnalysis:
    """Один проход кода Влада по одной компании. ops — сырые или после clean_operations."""
    as_of = pd.Timestamp(as_of).normalize()
    if not set(CLEAN_FLAGS) <= set(ops.columns):
        ops = clean_operations(ops)
    past = ops[ops["operation_date"] <= as_of]          # утечка: всё дальше — только по прошлому
    service = past[list(CLEAN_FLAGS)].any(axis=1)
    biz = past[~service]

    labels = pd.DataFrame({"category": pd.Series(None, index=ops.index, dtype=object),
                           "category_name": pd.Series(None, index=ops.index, dtype=object),
                           "mandatory": False, "is_regular": False,
                           "stream_id": pd.Series(None, index=ops.index, dtype=object)})
    labels.loc[service[service].index, ["category", "category_name"]] = _service_labels(past[service]).to_numpy()

    silent = _silent_working_days(past, as_of)
    if biz.empty:
        empty = pd.DataFrame()
        return RegularAnalysis(labels, empty, empty, as_of, silent)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        streams, prognosis, allp = vlad.analyze_payments(biz.assign(_row=biz.index), as_of, horizon_days,
                                                         config=VLAD_CONFIG)
    streams.attrs = {}      # у Влада там копия всех операций и сводки — нам не нужны
    idx = allp["_row"].to_numpy()
    labels.loc[idx, "category"] = allp["category"].to_numpy()
    labels.loc[idx, "category_name"] = allp["category_name"].to_numpy()
    labels.loc[idx, "mandatory"] = allp["mandatory"].astype(bool).to_numpy()
    regular = allp["is_regular"].astype(bool) & ~allp["category"].isin(NEVER_REGULAR)
    # поток с несколькими платежами в месяц, который Влад не разбил на под-потоки, склеился бы в один
    # месячный платёж на дату первого — такие оставляем модели (эквайринг, ежедневные закупки)
    frequent = _frequent_streams(allp[regular])
    regular &= ~allp["stream_id"].isin(frequent)
    labels.loc[idx, "is_regular"] = regular.to_numpy()
    labels.loc[idx, "stream_id"] = allp["stream_id"].where(regular).to_numpy()
    keys = pd.Series(None, index=ops.index, dtype=object)
    keys.loc[idx] = allp["counterparty_key"].astype(str).to_numpy()
    payments = pd.DataFrame({"stream_id": allp["stream_id"].where(regular).to_numpy(),
                             "operation_date": pd.to_datetime(allp["operation_date"]).to_numpy()}).dropna()
    if not streams.empty:
        streams = streams[~streams["category"].isin(NEVER_REGULAR) & ~streams["stream_id"].isin(frequent)]
        streams = streams.reset_index(drop=True)
        prognosis = prognosis[prognosis["stream_id"].isin(streams["stream_id"])]
    return RegularAnalysis(labels, streams, prognosis, as_of, silent, payments, keys)


def _silent_working_days(past: pd.DataFrame, as_of: pd.Timestamp) -> int:
    real = past[~past["is_duplicate"]]
    if real.empty:
        return 0
    wd = all_working_days()
    return int(((wd > real["operation_date"].max()) & (wd <= as_of)).sum())


def _frequent_streams(rows: pd.DataFrame, max_per_month: float = 1.0) -> set[str]:
    per_month = rows.groupby(["stream_id", rows["operation_date"].dt.to_period("M")]).size()
    med = per_month.groupby(level=0).median()
    return set(med[med > max_per_month].index)


def _service_labels(rows: pd.DataFrame) -> pd.DataFrame:
    inflow = rows["direction"] == "Поступление"
    cat = pd.Series("other", index=rows.index)
    cat[rows["is_error_refund"]] = "refund"
    cat[rows["is_own_transfer"]] = "own_transfer"
    cat[rows["is_founder_financing"]] = inflow[rows["is_founder_financing"]].map(
        {True: "owner_injection", False: "owner_withdrawal"})
    name = cat.map(lambda c: CATEGORIES[c][1])
    name[rows["is_duplicate"]] = "Дубль операции"
    return pd.DataFrame({"category": cat, "category_name": name})


def label_operations(ops: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Те же строки + разметка. Строки после as_of не размечаются (category=None, is_regular=False)."""
    return ops.join(analyze(ops, as_of).labels)


def is_regular(ops: pd.DataFrame, as_of: date) -> pd.Series:
    return analyze(ops, as_of).labels["is_regular"].astype(bool)


def find_regular(ops: pd.DataFrame, as_of: date, horizon_days: int = 30,
                 config: RegularConfig = RegularConfig()) -> list[Event]:
    return to_events(analyze(ops, as_of, horizon_days), horizon_days, config)


def to_events(ra: RegularAnalysis, horizon_days: int = 30, config: RegularConfig = RegularConfig()) -> list[Event]:
    """Экземпляры потоков после as_of + просроченные обязательные платежи и поступления."""
    if ra.streams.empty:
        return []
    end = ra.as_of + pd.Timedelta(days=horizon_days)
    st = ra.streams.set_index("stream_id")
    events = []
    for r in ra.prognosis.itertuples(index=False):
        d = pd.Timestamp(r.date)
        if ra.as_of < d <= end:
            events.append(_event(d, float(r.signed_amount), st.loc[r.stream_id], r.stream_id,
                                 float(st.at[r.stream_id, "gap_conf"])))
    first_after = next_working_day(ra.as_of)
    for sid, s in st.iterrows():
        missed = _missed_dates(s, ra.as_of)
        inflow = "поступл" in str(s["direction"])
        if not missed or not (inflow or s["mandatory"]):
            continue
        amount = float(s["predicted_amount"]) * len(missed) * (1 if inflow else -1)
        conf = overdue_receipt_confidence(s, sid, ra.payments, missed[0], ra.as_of, config) if inflow else 1.0
        events.append(_event(first_after, amount, s, sid, conf, tuple(d.date() for d in missed)))
    if ra.silent_wd > config.stale_after_wd:
        # v4 Влада считает «уснувший» поток от конца данных, а не от as_of: у замолчавшей выписки потоки
        # живы — платежи по ним менее вероятны
        events = [replace(e, confidence=e.confidence * config.stale_factor) for e in events]
    return sorted(events, key=lambda e: (e.date, e.amount))


def _missed_dates(s: pd.Series, as_of: pd.Timestamp) -> list[pd.Timestamp]:
    """Ожидаемые даты потока ≤ as_of, когда платежа не было (у Влада следующий после последнего)."""
    step = max(1, int(s["months_ahead"]))
    raw = pd.Timestamp(s["predicted_next_date_raw"])
    out = []
    cfg = {**vlad.DEFAULT_CONFIG, **VLAD_CONFIG}
    while (d := vlad._adjust_predicted_date(raw, s["category"], cfg)) <= as_of:
        out.append(d)
        raw += pd.DateOffset(months=step)
    return out


def overdue_receipt_confidence(s: pd.Series, stream_id: str, payments: pd.DataFrame, due: pd.Timestamp,
                               as_of: pd.Timestamp, config: RegularConfig = RegularConfig()) -> float:
    """Вероятность, что просроченное поступление всё-таки придёт, по истории этого потока ≤ as_of.

    Опоздание k рабочих дней (от due до as_of). Из прошлых периодов потока: сколько раз платёж пришёл
    с опозданием ≥ k (late) и сколько периодов пропущено совсем (skipped). confidence = (late + p) / (late +
    skipped + 1), p = overdue_inflow_prior: без истории — p, часто платит поздно — выше, часто пропускает — ниже."""
    dates = payments.loc[payments["stream_id"] == stream_id, "operation_date"]
    dates = pd.to_datetime(dates[dates <= as_of]).sort_values()
    if dates.empty:
        return config.overdue_inflow_prior
    wd = all_working_days()
    k = int(((wd > due) & (wd <= as_of)).sum())
    step = max(1, int(s["months_ahead"]))
    first = dates.groupby(dates.dt.to_period("M")).min()
    day = int(first.dt.day.median())
    cfg = {**vlad.DEFAULT_CONFIG, **VLAD_CONFIG}
    late = 0
    for m, d in first.items():
        expected = vlad._adjust_predicted_date(pd.Timestamp(m.year, m.month, min(day, m.days_in_month)),
                                               s["category"], cfg)
        late += int(((wd > expected) & (wd <= d)).sum()) >= max(k, 1)
    periods = pd.period_range(first.index[0], first.index[-1], freq="M")[::step]
    skipped = int((~periods.isin(first.index)).sum())
    p = config.overdue_inflow_prior
    conf = (late + p) / (late + skipped + 1)
    return float(min(max(conf, config.overdue_inflow_min), config.overdue_inflow_max))


def _event(d, amount, s, stream_id, conf, overdue=()) -> Event:
    key = str(s["counterparty_key"])
    return Event(date=pd.Timestamp(d).date(), amount=amount, category=str(s["category"]), source="regular",
                 confidence=min(max(conf, 0.0), 1.0),
                 counterparty_id=hashlib.sha1(key.encode()).hexdigest()[:10],   # не ИНН
                 mandatory=bool(s["mandatory"]), stream_id=stream_id, overdue_dates=overdue)


def merge_events(found: list[Event], user: list[Event]) -> list[Event]:
    """Событие пользователя с тем же stream_id заменяет найденные по истории с даты события."""
    since: dict[str, date] = {}
    for e in user:
        if e.stream_id:
            since[e.stream_id] = min(e.date, since.get(e.stream_id, e.date))
    kept = [e for e in found if not (e.stream_id in since and e.date >= since[e.stream_id])]
    return sorted(kept + list(user), key=lambda e: e.date)


def in_groups(category: str, groups: frozenset[str] | set[str] | None) -> bool:
    return groups is None or category in groups
