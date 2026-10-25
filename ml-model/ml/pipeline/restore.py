"""Эксперимент 8.5: восстановленный поток — обязательные платежи, перенесённые из-за нехватки денег, на своих датах.

    deferred_payments(ops, as_of)          перенесённые платежи на as_of: индекс операции, normal_date, late_wd
    restore_ops(ops, as_of)                те же операции, у перенесённых operation_date = нормальная дата
    restored_analysis(ops, as_of, ra, h)   разметка Влада та же, даты следующих платежей — по восстановленным

В выписке переносов не видно: владелец, у которого нет денег на ЕНП или аренду, платит позже, остаток
не уходит в минус, и CF-метка разрыв не видит. Здесь перенос размечается так:
- поток — регулярный обязательный поток списаний кода Влада на as_of;
- нормальная дата периода — типичный день месяца потока (медиана первых платежей месяца по периодам
  без переносов, два прохода), у налогов — не позже срока уплаты; перенесена на рабочий день, как у Влада;
- платёж периода — первая не занятая операция потока в окне [нормальная − EARLY_WD, нормальная + max_late_wd]
  рабочих дней: так ловится и перенос через границу месяца (зарплата за 25-е, уплаченная 3-го);
- перенос — платёж позже нормальной даты хотя бы на min_late_wd рабочих дней, и на нормальную дату
  остаток на конец дня (последний известный ≤ этой даты) меньше суммы платежа.
Сумма не меняется.

Разметку (какие операции регулярные) восстановление не меняет: переносятся только операции регулярных
потоков, поэтому нерегулярная часть восстановленного ряда совпадает с фактической. Меняются даты событий:
у потоков с переносами следующая дата, шаг и уверенность пересчитываются кодом Влада (_forecast_stream)
по восстановленным датам. Код Влада заново по восстановленному ряду не запускается: два под-потока ЕНП,
сдвинутые на один срок уплаты, он не разделяет, и поток перестаёт быть регулярным.

Всё только по операциям ≤ as_of: перенесённый платёж уже состоялся (дата ≤ as_of),
нормальная дата раньше него, остаток берётся на нормальную дату.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import pandas as pd

from ml.data.calendar import all_working_days
from ml.pipeline import regular as reg
from ml.pipeline.vlad import analyze_payments as vlad

EARLY_WD = 5
DEFERRED_COLUMNS = ["stream_id", "category", "normal_date", "operation_date", "late_wd"]


@dataclass(frozen=True)
class RestoreConfig:
    min_late_wd: int = 2       # опоздание на 1 р.д. — обычный разброс даты, не перенос
    max_late_wd: int = 15      # позже — уже не этот период
    shortfall_ratio: float = 1.0   # нехватка: остаток на нормальную дату < ratio × сумма платежа


def deferred_payments(ops: pd.DataFrame, as_of: date, ra: reg.RegularAnalysis | None = None,
                      config: RestoreConfig = RestoreConfig()) -> pd.DataFrame:
    """ops — одна компания после clean_operations; ra — analyze(ops, as_of), если уже посчитан.
    Индекс результата — индекс операций ops; колонки DEFERRED_COLUMNS."""
    as_of = pd.Timestamp(as_of).normalize()
    ra = ra if ra is not None else reg.analyze(ops, as_of)
    empty = pd.DataFrame(columns=DEFERRED_COLUMNS)
    if ra.streams.empty:
        return empty
    past = ops[(ops["operation_date"] <= as_of) & ~ops["is_duplicate"]]
    day_bal = past.groupby(past["operation_date"].dt.normalize())["balance_eod"].first().sort_index()
    if day_bal.empty:
        return empty
    lab = ra.labels.loc[past.index]
    out_streams = ra.streams[ra.streams["mandatory"].astype(bool)
                             & ~ra.streams["direction"].astype(str).str.contains("поступл")]
    wd = all_working_days()
    parts = []
    for s in out_streams.itertuples(index=False):
        rows = past[lab["stream_id"] == s.stream_id]
        if len(rows) >= 2:
            parts.append(_stream_deferrals(rows, s.stream_id, s.category, day_bal, wd, config))
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts) if parts else empty


def _stream_deferrals(rows: pd.DataFrame, stream_id: str, category: str, day_bal: pd.Series,
                      wd: pd.DatetimeIndex, cfg: RestoreConfig) -> pd.DataFrame:
    rows = rows.sort_values("operation_date")
    dates = rows["operation_date"].dt.normalize()
    months = pd.period_range(dates.iloc[0].to_period("M"), dates.iloc[-1].to_period("M"), freq="M")
    first_days = dates.groupby(dates.dt.to_period("M")).min().dt.day
    late_months: set = set()
    found = pd.DataFrame(columns=DEFERRED_COLUMNS)
    for _ in range(2):   # второй проход: типичный день без месяцев с переносами
        on_time = first_days[~first_days.index.isin(late_months)]
        day = int(np.median(on_time if len(on_time) else first_days))
        if category in vlad.TAX_CATEGORIES:
            day = min(day, vlad.DEFAULT_CONFIG["tax_deadline_day"])
        found = _match(rows, dates, months, day, stream_id, category, day_bal, wd, cfg)
        late_months = {pd.Timestamp(d).to_period("M") for d in found["normal_date"]}
    return found


def _match(rows, dates, months, day, stream_id, category, day_bal, wd, cfg) -> pd.DataFrame:
    vcfg = {**vlad.DEFAULT_CONFIG, **reg.VLAD_CONFIG}
    pos = wd.searchsorted(dates.to_numpy())
    used = np.zeros(len(rows), dtype=bool)
    out = []
    for m in months:
        normal = vlad._adjust_predicted_date(pd.Timestamp(m.year, m.month, min(day, m.days_in_month)),
                                             category, vcfg)
        p = int(wd.searchsorted(normal))
        cand = np.flatnonzero(~used & (pos >= p - EARLY_WD) & (pos <= p + cfg.max_late_wd))
        if not len(cand):
            continue
        i = cand[0]
        same_day = np.flatnonzero(~used & (dates.to_numpy() == dates.iloc[i]))
        used[same_day] = True
        late = int(pos[i] - p)
        if late < cfg.min_late_wd:
            continue
        k = int(day_bal.index.searchsorted(normal, side="right")) - 1
        amount = float(rows["amount"].iloc[same_day].sum())
        if k < 0 or day_bal.iloc[k] >= cfg.shortfall_ratio * amount:
            continue   # деньги на нормальную дату были — опоздание не из-за нехватки
        for j in same_day:
            out.append((rows.index[j], stream_id, category, normal, dates.iloc[j], late))
    df = pd.DataFrame(out, columns=["index", *DEFERRED_COLUMNS])
    return df.set_index("index").rename_axis(None)


def restore_ops(ops: pd.DataFrame, as_of: date, ra: reg.RegularAnalysis | None = None,
                config: RestoreConfig = RestoreConfig()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Операции восстановленного ряда (индекс и все колонки как у ops) и таблица переносов.
    balance_eod не пересчитывается: остаток по восстановленному ряду не строим, он нужен только разметке."""
    d = deferred_payments(ops, as_of, ra, config)
    if d.empty:
        return ops, d
    out = ops.copy()
    out.loc[d.index, "operation_date"] = pd.to_datetime(d["normal_date"]).to_numpy()
    return out, d


def restored_analysis(ops: pd.DataFrame, as_of: date, ra: reg.RegularAnalysis, horizon_days: int = 30,
                      config: RestoreConfig = RestoreConfig()) -> reg.RegularAnalysis:
    """ra — analyze(ops, as_of, horizon_days). Потоки с переносами — с датами по восстановленному ряду."""
    ops_r, d = restore_ops(ops, as_of, ra, config)
    if d.empty:
        return ra
    as_of = pd.Timestamp(as_of).normalize()
    vcfg = {**vlad.DEFAULT_CONFIG, **reg.VLAD_CONFIG}
    past = ops_r[(ops_r["operation_date"] <= as_of) & ~ops_r["is_duplicate"]]
    sid = ra.labels.loc[past.index, "stream_id"]
    streams = ra.streams.copy()
    for i in np.flatnonzero(streams["stream_id"].isin(set(d["stream_id"]))):
        s = streams.iloc[i]
        rows = past[sid == s["stream_id"]]
        dates = rows["operation_date"].dt.normalize()
        monthly = (rows.assign(month=dates.dt.to_period("M"), first_date=dates)
                   .groupby("month", as_index=False).agg(amount=("amount", "sum"), first_date=("first_date", "min")))
        monthly["first_day"] = monthly["first_date"].dt.day
        fc = vlad._forecast_stream(monthly, s["category"], s["cadence"], vcfg)
        for k, v in fc.items():
            streams.iat[i, streams.columns.get_loc(k)] = v
    streams["is_overdue"] = pd.to_datetime(streams["predicted_next_date"]) < as_of
    prognosis = vlad._build_prognosis(streams, as_of, horizon_days, vcfg)
    return replace(ra, streams=streams, prognosis=prognosis)
