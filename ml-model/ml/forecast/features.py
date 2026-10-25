"""Признаки глобальной модели потока. Строка = (company_id, as_of, h), h — рабочие дни вперёд.

Дневные признаки на дне t считаются только по дням ≤ t (trailing-окна, сдвиги, ffill),
поэтому строки для as_of можно строить по полной панели без утечки.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.calendar import CALENDAR_FEATURES, calendar_table, week_end_working_days, wd_position

FLOWS = ("in", "out")
LAGS = (1, 2, 3, 4, 5, 10, 20)     # lag_k = значение k−1 рабочих дней до as_of
WINDOWS = (5, 20, 60)
DOW_WEEKS = 8
YEAR_WD = 248                      # рабочих дней в году
FUNDING_WINDOW = 60                # рабочих дней: «на чьи деньги живёт» компания
ID_COLS = ["company_id", "as_of", "h", "target_date"]
CAT_FEATURES = ["industry", "legal_form"]


# эксперимент 8.1: остаток на as_of (всё в оборотах scale, только по дням ≤ as_of)
BALANCE_FEATURES = ["bal_scale", "bal_min20_scale", "bal_low1_60", "bal_low2_60", "days_since_big_in"]
# эксперимент 8.2: тот же отрезок год назад — поток за 5/20 р.д. после (as_of − год), отношение «сейчас / год назад»
LAST_YEAR_FEATURES = [f"{f}_{k}" for f in ("in", "out") for k in ("ly5", "ly20", "ratio_ly20")]
FEATURE_SETS = {
    "base": [],
    "balance": BALANCE_FEATURES,
    "last_year": LAST_YEAR_FEATURES,
    "balance_last_year": BALANCE_FEATURES + LAST_YEAR_FEATURES,
}
BIG_INFLOW_K = 5.0     # «крупное поступление» — больше 5 дневных оборотов


def feature_columns(feature_set: str = "base") -> list[str]:
    cols = [*CALENDAR_FEATURES, "h", "cal_days_ahead", "hist_len", "log_scale", "gap_recent20"]
    for f in FLOWS:
        cols += [f"{f}_lag{k}" for k in LAGS]
        cols += [f"{f}_mean{w}" for w in WINDOWS]
        cols += [f"{f}_std20", f"{f}_nz60", f"{f}_dow_target", f"{f}_yoy_level", f"{f}_yoy_ratio"]
    return cols + FEATURE_SETS[feature_set] + CAT_FEATURES


ALL_FEATURES = feature_columns("balance_last_year")


def day_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Признаки на конец каждого дня панели (в рублях, нормировка — в make_rows)."""
    p = panel
    cid = p["company_id"]
    dow = p["date"].dt.day_of_week.clip(upper=4)   # рабочая суббота ≈ пятница
    out = p[["company_id", "date", "scale", "hist_len", "industry", "legal_form"]].copy()
    out["wd_pos"] = wd_position(p["date"])
    for f in FLOWS:
        y = p[f"y_{f}"].where(~p["gap_in_data"])
        g = y.groupby(cid)
        for k in LAGS:
            out[f"raw_{f}_lag{k}"] = g.shift(k - 1)
        for w in WINDOWS:
            out[f"raw_{f}_mean{w}"] = g.transform(lambda s, w=w: s.rolling(w, min_periods=max(2, w // 4)).mean())
        out[f"raw_{f}_std20"] = g.transform(lambda s: s.rolling(20, min_periods=5).std())
        out[f"raw_{f}_sum5"] = g.transform(lambda s: s.rolling(5, min_periods=5).sum())     # 8.2
        out[f"raw_{f}_sum20"] = g.transform(lambda s: s.rolling(20, min_periods=15).sum())
        nz = (y > 0).astype(float).where(y.notna())
        out[f"{f}_nz60"] = nz.groupby(cid).transform(lambda s: s.rolling(60, min_periods=5).mean())
        dm = y.groupby([cid, dow]).transform(lambda s: s.rolling(DOW_WEEKS, min_periods=2).mean())
        for d in range(5):
            out[f"raw_{f}_dow{d}"] = dm.where(dow == d).groupby(cid).ffill()
    # 8.1: остаток в оборотах того же дня
    bal, sc = p["balance_eod"], p["scale"]
    gb = bal.groupby(cid)
    out["bal_scale"] = bal / sc
    out["bal_min20_scale"] = gb.transform(lambda s: s.rolling(20, min_periods=5).min()) / sc
    for k in (1, 2):
        low = (bal < k * sc).astype(float)
        out[f"bal_low{k}_60"] = low.groupby(cid).transform(lambda s: s.rolling(60, min_periods=10).sum())
    big = p["in_flow"] > BIG_INFLOW_K * sc
    pos = pd.Series(np.arange(len(p)), index=p.index)
    last_big = pos.where(big).groupby(cid).ffill()
    out["days_since_big_in"] = (pos - last_big).astype(float)
    gap = p["gap_in_data"].astype(float)
    out["gap_recent20"] = gap.groupby(cid).transform(lambda s: s.rolling(20, min_periods=1).max())
    return out


def funding_window(hist: pd.DataFrame, window: int = FUNDING_WINDOW) -> dict:
    """Финансирование за последние window рабочих дней истории одной компании (в рублях).

    hist — панель компании до as_of включительно. founder_share = деньги учредителя / расходы потока.
    """
    w = hist.iloc[-window:]
    y_out = float(w["y_out"].sum())
    founder = float(w["founder_in"].sum())
    days = max((w["date"].iloc[-1] - w["date"].iloc[0]).days + 1, 1)
    with_rev = hist.loc[hist["y_in"] > 0, "date"]
    return {
        "founder_in": founder, "loan_in": float(w["loan_in"].sum()),
        "y_in": float(w["y_in"].sum()), "y_out": y_out,
        "founder_share": founder / y_out if y_out > 0 else np.nan,
        "founder_per_month": founder / days * 30.4,
        "last_revenue": with_rev.iloc[-1] if len(with_rev) else None,
        "first_date": hist["date"].iloc[0], "window_start": w["date"].iloc[0],
    }


def weekly_origins(panel: pd.DataFrame, start=None, end=None, min_history: int = 20) -> pd.DataFrame:
    """Недельные точки прогноза: последний рабочий день недели, история ≥ min_history, не в пропуске."""
    p = panel[panel["date"].isin(week_end_working_days())]
    m = (p["hist_len"] >= min_history) & ~p["gap_in_data"]
    if start is not None:
        m &= p["date"] >= pd.Timestamp(start)
    if end is not None:
        m &= p["date"] <= pd.Timestamp(end)
    return p.loc[m, ["company_id", "date"]].rename(columns={"date": "as_of"}).reset_index(drop=True)


def make_rows(panel: pd.DataFrame, origins: pd.DataFrame, horizon: int,
              day_feats: pd.DataFrame | None = None) -> pd.DataFrame:
    """Строки признаков без целей. origins: company_id, as_of (рабочий день внутри панели)."""
    df = day_features(panel) if day_feats is None else day_feats
    o = origins[["company_id", "as_of"]].merge(
        df, left_on=["company_id", "as_of"], right_on=["company_id", "date"], how="inner",
    ).drop(columns="date")
    rows = o.loc[o.index.repeat(horizon)].reset_index(drop=True)
    rows["h"] = np.tile(np.arange(1, horizon + 1), len(o))

    cal = calendar_table()
    tpos = rows["wd_pos"].to_numpy() + rows["h"].to_numpy()
    if len(tpos) and tpos.max() >= len(cal):
        raise ValueError("горизонт выходит за конец календаря")
    rows["target_date"] = cal["date"].to_numpy()[tpos]
    for c in CALENDAR_FEATURES:
        rows[c] = cal[c].to_numpy()[tpos]
    rows["cal_days_ahead"] = (rows["target_date"] - rows["as_of"]).dt.days

    s = rows["scale"]
    idx = np.arange(len(rows))
    tdow = np.minimum(rows["dow"].to_numpy(), 4)
    for f in FLOWS:
        for k in LAGS:
            rows[f"{f}_lag{k}"] = rows[f"raw_{f}_lag{k}"] / s
        for w in WINDOWS:
            rows[f"{f}_mean{w}"] = rows[f"raw_{f}_mean{w}"] / s
        rows[f"{f}_std20"] = rows[f"raw_{f}_std20"] / s
        dow_cols = [f"raw_{f}_dow{d}" for d in range(5)]
        rows[f"raw_{f}_dow_target"] = rows[dow_cols].to_numpy()[idx, tdow]
        rows[f"{f}_dow_target"] = rows[f"raw_{f}_dow_target"] / s
        rows = rows.drop(columns=dow_cols)
    rows = _add_year_ago(rows, df)
    rows = _add_last_year_window(rows, df)
    rows["log_scale"] = np.log10(s)
    for c in CAT_FEATURES:
        rows[c] = rows[c].astype("category")
    return rows.copy()      # дефрагментация: колонки добавлялись по одной


def _add_last_year_window(rows: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """8.2: поток за 5/20 р.д. после (as_of − год) в оборотах и отношение mean20 сейчас / mean20 год назад.
    Нет года истории — пропуск (merge не найдёт строку)."""
    keys = ["company_id", "wd_pos"]
    cols = [f"raw_{f}_{k}" for f in FLOWS for k in ("sum5", "sum20", "mean20")]
    look = df[keys + cols]
    at = lambda shift: rows[["company_id"]].assign(wd_pos=rows["wd_pos"] + shift).merge(look, on=keys, how="left")
    a5, a20, a0 = at(-YEAR_WD + 5), at(-YEAR_WD + 20), at(-YEAR_WD)
    s = rows["scale"].to_numpy()
    for f in FLOWS:
        rows[f"{f}_ly5"] = a5[f"raw_{f}_sum5"].to_numpy() / s
        rows[f"{f}_ly20"] = a20[f"raw_{f}_sum20"].to_numpy() / s
        with np.errstate(divide="ignore", invalid="ignore"):
            r = rows[f"raw_{f}_mean20"].to_numpy() / a0[f"raw_{f}_mean20"].to_numpy()
        rows[f"{f}_ratio_ly20"] = np.where(np.isfinite(r), r, np.nan)
    return rows


def _add_year_ago(rows: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Сезонность год назад: уровень потока около целевого дня год назад и его отношение к тогдашнему фону."""
    keys = ["company_id", "wd_pos"]
    look = df[keys + [f"raw_{f}_mean{w}" for f in FLOWS for w in (20, 60)]]
    # окно mean20 на дне (target − год + 10) покрывает ±10 рабочих дней вокруг целевого дня год назад
    around = rows[["company_id"]].assign(wd_pos=rows["wd_pos"] + rows["h"] - YEAR_WD + 10)
    base = rows[["company_id"]].assign(wd_pos=rows["wd_pos"] - YEAR_WD)
    a = around.merge(look, on=keys, how="left")
    b = base.merge(look, on=keys, how="left")
    for f in FLOWS:
        rows[f"{f}_yoy_level"] = a[f"raw_{f}_mean20"].to_numpy() / rows["scale"].to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = a[f"raw_{f}_mean20"].to_numpy() / b[f"raw_{f}_mean60"].to_numpy()
        rows[f"{f}_yoy_ratio"] = np.where(np.isfinite(ratio), ratio, np.nan)
    return rows


def attach_targets(rows: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Факт для обучения и оценки. Модели эти колонки не видят."""
    t = panel[["company_id", "date", "y_in", "y_out", "gap_in_data", "balance_eod", "cum_y", "gap_cum", "cum_rescue"]]
    t = t.rename(columns={"date": "target_date", "balance_eod": "bal_true", "cum_y": "cum_y_t",
                          "gap_cum": "gap_cum_t", "gap_in_data": "gap_t", "cum_rescue": "cum_rescue_t"})
    a = panel[["company_id", "date", "balance_eod", "cum_y", "gap_cum", "cum_rescue"]].rename(
        columns={"date": "as_of", "balance_eod": "bal_asof", "cum_y": "cum_y_asof", "gap_cum": "gap_cum_asof",
                 "cum_rescue": "cum_rescue_asof"})
    out = rows.merge(t, on=["company_id", "target_date"], how="left").merge(a, on=["company_id", "as_of"], how="left")
    out["target_valid"] = out["y_in"].notna() & ~out["gap_t"].fillna(True).astype(bool)
    out["gap_between"] = ~((out["gap_cum_t"] - out["gap_cum_asof"]) == 0)
    out["dflow_true"] = out["cum_y_t"] - out["cum_y_asof"]
    # спасающие поступления за дни a+1..a+h: остаток «без вмешательства» = bal_true − rescue_true
    out["rescue_true"] = out["cum_rescue_t"] - out["cum_rescue_asof"]
    for f in FLOWS:
        out[f"y_{f}_norm"] = out[f"y_{f}"] / out["scale"]
    return out.drop(columns=["cum_y_t", "cum_y_asof", "gap_cum_t", "gap_cum_asof", "gap_t",
                             "cum_rescue_t", "cum_rescue_asof"])
