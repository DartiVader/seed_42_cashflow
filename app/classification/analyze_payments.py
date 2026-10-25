"""
analyze_payments.py

Категории берутся из payment_categories.py (лежит рядом):
  правила -> контрагент -> d1-omni (опционально).
Сквозные категории для списаний: regular_payment, mandatory_payment.

Input: DataFrame of transactions (not CSV path).
        analyze_payments(ops, as_of, horizon_days)
"""

import re
import warnings
import calendar
import statistics
import pandas as pd
from typing import Optional

from app.classification.payment_categories import CATEGORIES, GROUPS, MANDATORY, SPECIAL, categorizer

def _ru(code: str) -> str:
    return CATEGORIES[code][1]
# =============================== CONFIG =====================================
DEFAULT_CONFIG = {
    "cadence_min_share":               0.75,
    "min_payments":                    3,
    "min_payments_seasonal":           2,
    "amount_weight_decay":             0.85,
    "date_weight_decay":               0.85,
    "seasonal_min_gap":                10,
    "seasonal_max_gap":                14,
    "quarterly_min_payments":          4,
    "quarterly_min_gap":               3,
    "quarterly_max_gap":               4,
    "max_dormant_multiplier":          2.5,
    "max_dormant_multiplier_seasonal": 4.0,
    "tax_deadline_day":                28,
    "salary_split_min_gap_days":       5,
    "multi_split_min_gap_days":        5,
    "day_stdev_cap":          10.0,   # monthly
    "day_stdev_cap_seasonal": 30.0,   # seasonal — allows ~1 month drift → date_conf ≈ 0.5
    "tax_date_conf":          0.90,
    "min_confidence_component": 0.05,
    "high_variance_cv_threshold":       1.0,   # cv above this → median fallback
    "high_variance_median_window":      6,
    # business_day_calendar: callable(date)->bool, or collection of business
    # days from ml/data. None -> weekend-only + loud warning (не молча).
    "business_day_calendar":           None,
    "use_llm":                         False,
    "llm_workers":                     4,
}

def _ru(code: str) -> str:
    return CATEGORIES[code][1]


# ── All constants below MUST use the same representation as df["category"],
#    which is Russian (translated in _classify). Any English code here will
#    silently fail every `if category in ...` check.

TAX_CATEGORIES        = {_ru(c) for c in ("tax_enp", "tax_other")}
NON_STREAM_CATEGORIES = {_ru(c) for c in (
    "owner_injection", "own_transfer", "refund", "other",
    "loan_received", "owner_withdrawal",
)}

# ── Pinned substream names (single source of truth) ─────────────────────
SALARY_ADVANCE_NAME    = "Зарплата (аванс)"
SALARY_SETTLEMENT_NAME = "Зарплата (расчёт)"

MANDATORY_CATEGORIES  = {_ru(c) for c in MANDATORY} | {
    SALARY_ADVANCE_NAME, SALARY_SETTLEMENT_NAME,
}

NO_SPLIT_CATEGORIES   = TAX_CATEGORIES | {_ru(c) for c in (
    "bank_fee", "loan_repayment", "leasing",
    "revenue_acquiring", "revenue_sbp", "revenue_cash",
)}

CADENCE_SEASONAL = "сезонно"
CADENCE_RU = {
    "monthly":              "ежемесячно",
    "monthly (with skips)": "ежемесячно (с пропусками)",
    "bimonthly":            "раз в 2 месяца",
    "quarterly":            "ежеквартально",
    "seasonal":             CADENCE_SEASONAL,
}

_NAME_TO_GROUP = {v[1]: GROUPS[v[0]] for v in CATEGORIES.values()}
_NAME_TO_GROUP["Зарплата (аванс)"]    = GROUPS["staff"]
_NAME_TO_GROUP["Зарплата (расчёт)"]   = GROUPS["staff"]

STREAM_COLUMNS = [
    "stream_id", "sub_stream", "counterparty_key", "counterparty_name",
    "direction", "category", "cadence", "mandatory", "mandatory_reason",
    "active_months", "first_month", "last_month",
    "last_payment", "last_amount", "months_since_last",
    "months_ahead",
    "predicted_next_date", "predicted_next_date_raw",
    "date_window_low", "date_window_high",
    "predicted_amount", "amount_range_low", "amount_range_high",
    "day_stdev", "amount_cv", "gap_cv",
    "date_conf", "amount_conf", "gap_conf",
    "confidence", "confidence_label", "is_overdue",
]

# ============================ BUSINESS DAYS =================================
def _is_business_day(d, cfg) -> bool:
    cal = cfg.get("business_day_calendar")
    d_norm = pd.Timestamp(d).normalize()
    if cal is None:
        return d_norm.weekday() < 5
    if callable(cal):
        return bool(cal(d_norm))
    try:
        return (d_norm in cal) or (d_norm.date() in cal)
    except TypeError:
        return d_norm in cal


def _shift_to_business_day(d, cfg) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    while not _is_business_day(d, cfg):
        d += pd.Timedelta(days=1)
    return d


def _adjust_predicted_date(d, category, cfg) -> pd.Timestamp:
    if category in TAX_CATEGORIES:
        day = min(cfg["tax_deadline_day"],
                  calendar.monthrange(d.year, d.month)[1])
        return _shift_to_business_day(pd.Timestamp(d.year, d.month, day), cfg)
    return _shift_to_business_day(d, cfg)


def _warn_if_no_calendar(cfg) -> None:
    if cfg.get("business_day_calendar") is None:
        warnings.warn(
            "business_day_calendar не задан — работаем по выходным (сб/вс). "
            "Российские праздники не будут учтены. Передайте календарь из "
            "ml/data через config={'business_day_calendar': <callable|set>}.",
            stacklevel=3,
        )


# =============================== INPUT ======================================
def _clean_inn(x) -> str:
    """NaN → '', drop the '.0' that pandas leaves on float→str casts."""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s
def _clean_inn(x) -> str:
    """NaN → '', drop the '.0' that pandas leaves on float→str casts."""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _normalize_basic(ops: pd.DataFrame) -> pd.DataFrame:
    """
    Pure per-row normalization. No cross-row operations, no INN merge.

    Puts the frame in a state where `operation_date <= as_of` can be applied.
    """
    df = ops.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # --- dates ---
    if pd.api.types.is_datetime64_any_dtype(df["operation_date"]):
        df["operation_date_raw"] = df["operation_date"].dt.strftime("%Y-%m-%d")
    else:
        df["operation_date_raw"] = df["operation_date"].astype(str)
        df["operation_date"] = pd.to_datetime(
            df["operation_date"], errors="coerce")
    df["date_valid"] = df["operation_date"].notna()

    # --- amount ---
    if pd.api.types.is_numeric_dtype(df["amount"]):
        df["amount"] = df["amount"].abs()
    else:
        df["amount"] = pd.to_numeric(
            df["amount"].astype(str)
                       .str.replace("\xa0", "", regex=False)
                       .str.replace(" ", "", regex=False)
                       .str.replace(",", ".", regex=False),
            errors="coerce",
        ).fillna(0.0).abs()

    # --- scalar string fields (no aggregation yet) ---
    df["direction"]         = df["direction"].astype(str).str.strip().str.lower()
    df["counterparty_inn"]  = df["counterparty_inn"].apply(_clean_inn)
    df["counterparty_name"] = df["counterparty_name"].apply(
        lambda x: "" if pd.isna(x) else str(x).strip())
    df["payment_purpose"]   = df["payment_purpose"].apply(
        lambda x: "" if pd.isna(x) else str(x))

    return df.reset_index(drop=True)


def _resolve_counterparty_keys(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-row counterparty resolution. MUST run only on the time-truncated
    frame — otherwise a name→INN mapping learned from a future transaction
    leaks back into past rows.
    """
    df = df.copy()

    INVALID_INN = {"", "nan", "none", "null", "0", "nat"}
    inn_valid = ~df["counterparty_inn"].str.lower().isin(INVALID_INN)

    # name → INN only from unambiguous names (nunique == 1)
    ambiguous = (
        df.loc[inn_valid]
          .groupby("counterparty_name")["counterparty_inn"]
          .nunique()
    )
    unambiguous_names = set(ambiguous[ambiguous == 1].index)
    name_to_inn = (
        df.loc[inn_valid & df["counterparty_name"].isin(unambiguous_names)]
          .drop_duplicates("counterparty_name")
          .set_index("counterparty_name")["counterparty_inn"]
    )

    fill_mask = (~inn_valid) & df["counterparty_name"].isin(name_to_inn.index)
    if fill_mask.any():
        df.loc[fill_mask, "counterparty_inn"] = (
            df.loc[fill_mask, "counterparty_name"].map(name_to_inn)
        )
        inn_valid = ~df["counterparty_inn"].str.lower().isin(INVALID_INN)

    df["counterparty_key"] = df["counterparty_inn"].where(
        inn_valid, "NAME:" + df["counterparty_name"])

    return df


# =============================== CLASSIFY ===================================
def _base_category(cat: str) -> str:
    return "Зарплата" if str(cat).startswith("Зарплата") else cat


def _category_name(cat: str) -> str:
    """Русское имя для отображения; для под-потоков зарплаты — базовое."""
    return _base_category(cat)


def _category_group(cat: str) -> str:
    return _NAME_TO_GROUP.get(cat, GROUPS["technical"])


def _assign_salary_substreams(df, cfg):
    df = df.copy()
    for _, grp in df[df["category"] == _ru("salary")].groupby(
            ["counterparty_key", "direction"]):

        purpose   = grp["payment_purpose"].str.lower()
        is_adv    = purpose.str.contains(r"аванс", regex=True, na=False)
        is_settle = purpose.str.contains(r"расч[её]т|окончательн",
                                         regex=True, na=False)

        if is_adv.any() and is_settle.any():
            adv_idx = grp.index[is_adv]
            set_idx = grp.index[is_settle & ~is_adv]
            if (len(adv_idx) >= cfg["min_payments"]
                    and len(set_idx) >= cfg["min_payments"]):
                df.loc[adv_idx, "category"] = "Зарплата (аванс)"
                df.loc[set_idx, "category"] = "Зарплата (расчёт)"
                continue

        valid = grp[grp["date_valid"]]
        if len(valid) < cfg["min_payments"] * 2:
            continue

        days = valid["operation_date"].dt.day
        unique_days = sorted(days.unique())
        if len(unique_days) < 2:
            continue
        max_gap, split_idx = 0, None
        for i in range(len(unique_days) - 1):
            g = unique_days[i + 1] - unique_days[i]
            if g > max_gap:
                max_gap, split_idx = g, i
        if max_gap < cfg["salary_split_min_gap_days"]:
            continue

        split_day = unique_days[split_idx]
        early_idx = valid.index[days <= split_day]
        late_idx  = valid.index[days >  split_day]
        early_m = valid.loc[early_idx, "operation_date"].dt.to_period("M").nunique()
        late_m  = valid.loc[late_idx,  "operation_date"].dt.to_period("M").nunique()
        if early_m < cfg["min_payments"] or late_m < cfg["min_payments"]:
            continue

        df.loc[early_idx, "category"] = "Зарплата (расчёт)"
        df.loc[late_idx,  "category"] = "Зарплата (аванс)"
    return df


def _classify(df, cfg):
    df = df.copy()
    res = categorizer(df, use_llm=cfg.get("use_llm", False),
                      workers=cfg.get("llm_workers", 4))
    df["category"] = res["category"].map(_ru)
    df["category_method"] = res["method"]
    df["category_confidence"] = res["confidence"]
    return _assign_salary_substreams(df, cfg)


# ========================= MULTI-PAYMENT / MONTH SPLIT ======================
def _split_multi_per_month(df, cfg):
    """
    Группы с медианой >1 платежа в месяц дробим на под-потоки по кластеризации
    дня месяца. Добавляет колонку `sub_stream` (0 для обычных, 0..K-1 для
    разбитых). Строки с невалидной датой всегда получают sub_stream=0.
    """
    df = df.copy()
    df["sub_stream"] = 0

    for (key, direction, category), grp in df.groupby(
            ["counterparty_key", "direction", "category"]):

        valid = grp[grp["date_valid"]]
        if len(valid) < cfg["min_payments"] * 2:
            continue
        if category in NO_SPLIT_CATEGORIES:
            continue
        months = valid["operation_date"].dt.to_period("M")
        per_month = months.value_counts()
        if len(per_month) < cfg["min_payments"]:
            continue

        median_ops = per_month.median()
        if median_ops < 2:
            continue

        k = int(round(median_ops))
        days = valid["operation_date"].dt.day
        unique_days = sorted(days.unique())
        if len(unique_days) < k:
            continue

        gaps = [unique_days[i + 1] - unique_days[i]
                for i in range(len(unique_days) - 1)]
        split_indices = sorted(
            sorted(range(len(gaps)), key=lambda i: gaps[i], reverse=True)[:k - 1]
        )
        boundaries = [unique_days[i] for i in split_indices]

        # слишком близкие кластеры не отделяем
        if any(gaps[i] < cfg["multi_split_min_gap_days"]
               for i in split_indices):
            continue

        def _assign_sub(d):
            s = 0
            for b in boundaries:
                if d > b:
                    s += 1
            return s

        sub = days.map(_assign_sub)

        # каждый под-поток должен иметь >= min_payments месяцев
        ok = True
        for s in range(k):
            n_months = valid.loc[sub == s,
                                 "operation_date"].dt.to_period("M").nunique()
            if n_months < cfg["min_payments"]:
                ok = False
                break
        if not ok:
            continue

        df.loc[valid.index, "sub_stream"] = sub

    return df


# =============================== CADENCE ====================================
def _classify_cadence(gaps, cfg) -> Optional[str]:
    n = len(gaps)
    if n == 0:
        return None
    share = cfg["cadence_min_share"]
    q_min_n = cfg.get("quarterly_min_payments", 4)
    q_lo, q_hi = cfg["quarterly_min_gap"], cfg["quarterly_max_gap"]

    s1   = sum(1 for g in gaps if g == 1) / n
    s12  = sum(1 for g in gaps if g in (1, 2)) / n
    sq   = sum(1 for g in gaps if q_lo <= g <= q_hi) / n
    s23  = sum(1 for g in gaps if g in (2, 3)) / n
    s12m = sum(1 for g in gaps
               if cfg["seasonal_min_gap"] <= g <= cfg["seasonal_max_gap"]) / n

    if s1   >= share: return "ежемесячно"
    if s12  >= share: return "ежемесячно (с пропусками)"
    if sq   >= share and (n + 1) >= q_min_n: return "ежеквартально"
    if s23  >= share: return "раз в 2 месяца"
    if s12m >= share: return "сезонно"
    return None

# =============================== WEIGHTS ====================================
def _weighted_recent_mean(values, decay):
    n = len(values)
    if n == 0:
        return 0.0
    w = [decay ** (n - 1 - i) for i in range(n)]
    tot = sum(w)
    return sum(wi * v for wi, v in zip(w, values)) / tot if tot else 0.0


# =============================== FORECAST ===================================
def _forecast_stream(monthly, category, cadence, cfg):
    gaps = [(monthly["month"].iloc[i + 1] - monthly["month"].iloc[i]).n
            for i in range(len(monthly) - 1)]

    # ── cadence, not category ───────────────────────────────────────────────
    if cadence == CADENCE_SEASONAL:
        median_gap = statistics.median(gaps) if gaps else 12
        months_ahead = max(12, int(round(median_gap / 12) * 12))
    else:
        months_ahead = max(1, int(round(
            _weighted_recent_mean(gaps, cfg["date_weight_decay"]) if gaps else 1.0)))

    next_month = monthly["month"].iloc[-1] + months_ahead

    # ── seasonal: day-of-year, monthly: day-of-month ────────────────────────
    if cadence == CADENCE_SEASONAL:
        doys = monthly["first_date"].dt.dayofyear.tolist()
        weighted_doy = _weighted_recent_mean(doys, cfg["date_weight_decay"])
        day_stdev    = statistics.pstdev(doys) if len(doys) > 1 else 0.0
        max_doy      = 366 if calendar.isleap(next_month.year) else 365
        predicted_doy = min(max(1, int(round(weighted_doy))), max_doy)
        raw_date = (pd.Timestamp(next_month.year, 1, 1)
                    + pd.Timedelta(days=predicted_doy - 1))
    else:
        first_days   = monthly["first_day"].tolist()
        weighted_day = _weighted_recent_mean(first_days, cfg["date_weight_decay"])
        day_stdev    = statistics.pstdev(first_days) if len(first_days) > 1 else 0.0
        max_day      = calendar.monthrange(next_month.year, next_month.month)[1]
        predicted_day = min(int(round(weighted_day)), max_day)
        raw_date = pd.Timestamp(next_month.year, next_month.month, predicted_day)

    final_date = _adjust_predicted_date(raw_date, category, cfg)
    spread     = max(1, int(round(day_stdev)))
    date_low   = final_date - pd.Timedelta(days=spread)
    date_high  = final_date + pd.Timedelta(days=spread)

    amounts = monthly["amount"].tolist()
    mean_amt = statistics.mean(amounts)
    amt_stdev = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0
    amount_cv = amt_stdev / mean_amt if mean_amt > 0 else 0.0

    if amount_cv > cfg["high_variance_cv_threshold"]:
        # высокая дисперсия → медиана последних N месяцев
        recent = amounts[-cfg["high_variance_median_window"]:]
        predicted_amt = statistics.median(recent)
    else:
        predicted_amt = _weighted_recent_mean(amounts, cfg["amount_weight_decay"])

    gap_mean  = statistics.mean(gaps) if gaps else 1.0
    gap_stdev = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    gap_cv    = gap_stdev / gap_mean if gap_mean > 0 else 0.0

    # ── date confidence depends on *how* the day is determined ─────────────
    if category in TAX_CATEGORIES:
        date_conf = _confidence_component(0.0, cfg,
                                          fixed=cfg["tax_date_conf"])
    else:
        cap = (cfg["day_stdev_cap_seasonal"]
               if cadence == CADENCE_SEASONAL else cfg["day_stdev_cap"])
        date_conf = _confidence_component(day_stdev / cap, cfg)

    amount_conf = _confidence_component(amount_cv, cfg)
    gap_conf = _confidence_component(gap_cv, cfg)
    confidence = (date_conf * amount_conf * gap_conf) ** (1 / 3)

    return {
        "months_ahead": months_ahead,
        "predicted_next_date": final_date.strftime("%Y-%m-%d"),
        "predicted_next_date_raw": raw_date.strftime("%Y-%m-%d"),
        "date_window_low": date_low.strftime("%Y-%m-%d"),
        "date_window_high": date_high.strftime("%Y-%m-%d"),
        "predicted_amount": round(predicted_amt, 2),
        "amount_range_low": round(min(amounts), 2),
        "amount_range_high": round(max(amounts), 2),
        "day_stdev": round(day_stdev, 2),
        "amount_cv": round(amount_cv, 3),
        "gap_cv": round(gap_cv, 3),
        "date_conf": round(date_conf, 3),
        "amount_conf": round(amount_conf, 3),
        "gap_conf": round(gap_conf, 3),
        "confidence": round(confidence, 3),
    }


def _conf_label(c):
    return "HIGH" if c >= 0.80 else ("MEDIUM" if c >= 0.50 else "LOW")

def _confidence_component(penalty_cv: float, cfg: dict,
                          fixed: float | None = None) -> float:
    """
    Map a normalised penalty (cv, or stdev/cap) into a confidence score.

    Strictly positive — floored at `cfg['min_confidence_component']` so the
    geometric mean in `_forecast_stream` never collapses to 0.00.
    """
    floor = cfg.get("min_confidence_component", 0.05)
    if fixed is not None:
        return max(floor, min(1.0, fixed))
    return max(floor, 1.0 - penalty_cv)

def _build_stream_id(counterparty_key, category, direction,
                     sub_stream=0, n_subs=1) -> str:
    dir_short = "in" if "поступл" in str(direction) else "out"
    if n_subs > 1:
        return f"{counterparty_key}|{category}|s{sub_stream}|{dir_short}"
    return f"{counterparty_key}|{category}|{dir_short}"


# =============================== AGGREGATE ==================================
def _aggregate_monthly(df):
    df = df.copy()
    df["month"] = df["operation_date"].dt.to_period("M")
    monthly = (
        df.groupby(["counterparty_key", "direction", "category",
                    "sub_stream", "month"], as_index=False)
          .agg(amount=("amount", "sum"),
               first_date=("operation_date", "min"),
               name=("counterparty_name", "first"))
          .sort_values(["counterparty_key", "direction", "category",
                        "sub_stream", "month"])
    )
    monthly["first_day"] = monthly["first_date"].dt.day
    return monthly


def _compute_mandatory(category, direction):
    if "поступл" in str(direction):
        return False, "income — timing not controlled by company"
    if category in MANDATORY_CATEGORIES:
        return True, f"'{category}' — legal/contractual, cannot defer"
    return False, f"'{category}' — negotiable / can be deferred"

def _detect_and_forecast(monthly, cfg, as_of, data_max_date=None):
    rows = []
    if monthly.empty:
        return pd.DataFrame(columns=STREAM_COLUMNS)      # see Fix 2

    as_of_period     = pd.Period(as_of, "M")
    data_end_period  = monthly["month"].max()            # ← NEW

    n_subs_by_group = (
        monthly.groupby(["counterparty_key", "direction", "category"])
               ["sub_stream"].nunique().to_dict()
    )

    for (key, direction, category, sub_stream), grp in monthly.groupby(
            ["counterparty_key", "direction", "category", "sub_stream"]):

        if len(grp) < cfg["min_payments_seasonal"]:
            continue
        grp    = grp.reset_index(drop=True)
        months = grp["month"].tolist()
        gaps   = [(months[i + 1] - months[i]).n for i in range(len(months) - 1)]
        cadence = _classify_cadence(gaps, cfg)
        if cadence is None:
            continue
        min_req = (cfg["min_payments_seasonal"]
                   if cadence == CADENCE_SEASONAL else cfg["min_payments"])
        if len(grp) < min_req:
            continue

        # ── dormancy: relative to data end, NOT to as_of ───────────────
        median_gap        = statistics.median(gaps) if gaps else 1
        months_since_last = (data_end_period - months[-1]).n        # ← CHANGED
        mult = (cfg["max_dormant_multiplier_seasonal"]
                if cadence == CADENCE_SEASONAL else cfg["max_dormant_multiplier"])
        if months_since_last > mult * median_gap:
            continue
        # ───────────────────────────────────────────────────────────────

        fc = _forecast_stream(grp, category, cadence, cfg)
        mandatory, reason = _compute_mandatory(category, direction)
        n_subs = n_subs_by_group.get((key, direction, category), 1)

        rows.append({
            "stream_id":         _build_stream_id(key, category, direction,
                                                  sub_stream, n_subs),
            "sub_stream":        sub_stream,
            "counterparty_key":  key,
            "counterparty_name": grp["name"].iloc[0],
            "direction":         direction,
            "category":          category,
            "cadence":           cadence,
            "mandatory":         mandatory,
            "mandatory_reason":  reason,
            "active_months":     len(grp),
            "first_month":       str(months[0]),
            "last_month":        str(months[-1]),
            "last_payment":      grp["first_date"].iloc[-1].strftime("%Y-%m-%d"),
            "last_amount":       round(grp["amount"].iloc[-1], 2),
            "months_since_last": int(months_since_last),
            **fc,
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=STREAM_COLUMNS)

    result["confidence_label"] = result["confidence"].apply(_conf_label)


    if data_max_date is not None and not pd.isna(data_max_date):
        overdue_ref = pd.Timestamp(data_max_date).normalize()
    elif as_of is not None:
        overdue_ref = pd.Timestamp(as_of).normalize()
    else:
        overdue_ref = pd.Timestamp.today().normalize()

    result["is_overdue"] = (
            pd.to_datetime(result["predicted_next_date"]) < overdue_ref
    )
    return result


def _annotate_payments(classified, streams, cfg):
    df = classified.copy()

    stream_map = {
        (s["counterparty_key"], s["category"], s["direction"],
         int(s.get("sub_stream", 0))): s["stream_id"]
        for _, s in streams.iterrows()
    }
    df["stream_id"] = df.apply(
        lambda r: stream_map.get((
            r["counterparty_key"], r["category"], r["direction"],
            int(r.get("sub_stream", 0)))), axis=1)
    df["is_regular"] = df["stream_id"].notna()

    pairs = df[["category", "direction"]].drop_duplicates()
    mandatory_map = {
        (r["category"], r["direction"]):
            _compute_mandatory(r["category"], r["direction"])
        for _, r in pairs.iterrows()
    }
    df["mandatory"]        = df.apply(
        lambda r: mandatory_map[(r["category"], r["direction"])][0], axis=1)
    df["mandatory_reason"] = df.apply(
        lambda r: mandatory_map[(r["category"], r["direction"])][1], axis=1)

    is_out = ~df["direction"].str.contains("поступл", na=False)
    df["regular_payment"]   = df["is_regular"] & is_out
    df["mandatory_payment"] = df["mandatory"] & is_out
    df["category_name"]     = df["category"].map(_category_name)
    df["category_group"]    = df["category"].map(_category_group)

    def _labels(r):
        out = [r["category"]]
        if r["regular_payment"]:
            out.append("regular_payment")
        if r["mandatory_payment"]:
            out.append("mandatory_payment")
        return out

    df["categories"] = df.apply(_labels, axis=1)
    df["categories_names"] = df["categories"].map(
        lambda cs: " + ".join(SPECIAL.get(c) or _category_name(c) for c in cs))
    return df


# =============================== PROGNOSIS ==================================
def _build_prognosis(streams, data_max_date, horizon_days, cfg):
    cols = ["date", "counterparty_key", "counterparty_name",
            "direction", "category", "cadence", "sub_stream",
            "stream_id", "mandatory", "mandatory_reason",
            "predicted_amount", "signed_amount",
            "confidence", "confidence_label"]
    if streams.empty or data_max_date is None or pd.isna(data_max_date):
        return pd.DataFrame(columns=cols)

    # Forecast starts the day after the last known transaction
    start = pd.Timestamp(data_max_date).normalize()
    end   = start + pd.Timedelta(days=horizon_days)

    rows = []
    for _, row in streams.iterrows():
        gap      = max(1, int(row["months_ahead"]))
        category = row["category"]

        raw     = pd.Timestamp(row["predicted_next_date_raw"])
        shifted = _adjust_predicted_date(raw, category, cfg)
        while shifted < start:
            raw     = raw + pd.DateOffset(months=gap)
            shifted = _adjust_predicted_date(raw, category, cfg)

        amount = float(row["predicted_amount"])
        signed = amount if "поступл" in str(row["direction"]) else -amount

        while shifted <= end:
            rows.append({
                "date":              shifted.strftime("%Y-%m-%d"),
                "counterparty_key":  row["counterparty_key"],
                "counterparty_name": row["counterparty_name"],
                "direction":         row["direction"],
                "category":          category,
                "cadence":           row["cadence"],
                "sub_stream":        row["sub_stream"],
                "stream_id":         row["stream_id"],
                "mandatory":         row["mandatory"],
                "mandatory_reason":  row["mandatory_reason"],
                "predicted_amount":  round(amount, 2),
                "signed_amount":     round(signed, 2),
                "confidence":        row["confidence"],
                "confidence_label":  row["confidence_label"],
            })
            raw     = raw + pd.DateOffset(months=gap)
            shifted = _adjust_predicted_date(raw, category, cfg)

    return (pd.DataFrame(rows, columns=cols)
              .sort_values(["date", "counterparty_key"])
              .reset_index(drop=True))


def daily_totals(prognosis_df):
    if prognosis_df.empty:
        return pd.DataFrame(columns=["date", "income", "outcome", "net", "payments"])
    df = prognosis_df.copy()
    df["income"]  = df["signed_amount"].where(df["signed_amount"] > 0, 0.0)
    df["outcome"] = df["signed_amount"].where(df["signed_amount"] < 0, 0.0)
    daily = (df.groupby("date", as_index=False)
               .agg(income =("income", "sum"),
                    outcome=("outcome", "sum"),
                    payments=("signed_amount", "count")))
    daily["net"] = daily["income"] + daily["outcome"]
    return daily


# =========================== YEARLY AGGREGATION =============================
YEARLY_COLUMNS = [
    "year", "category", "direction", "mandatory",
    "payment_count", "total_amount", "avg_amount", "active_streams",
]
YEARLY_SEASONAL_COLUMNS = [
    "year", "season", "category", "direction", "mandatory",
    "payment_count", "total_amount", "avg_amount", "active_streams",
]


def yearly_summary(classified_df, categories_df, by_season=False):
    needed = ["counterparty_key", "direction", "category",
              "sub_stream", "mandatory"]
    out_cols = (YEARLY_SEASONAL_COLUMNS if by_season else YEARLY_COLUMNS)

    if categories_df is None or categories_df.empty or \
       not set(needed).issubset(categories_df.columns):
        return pd.DataFrame(columns=out_cols)

    detected = categories_df[needed].drop_duplicates()
    merged = classified_df.merge(
        detected,
        on=["counterparty_key", "direction", "category", "sub_stream"],
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame(columns=out_cols)

    merged = merged.copy()
    merged["year"] = merged["operation_date"].dt.year

    if by_season:
        def _to_season(m):
            if m in (12, 1, 2): return "winter"
            if m in (3, 4, 5):  return "spring"
            if m in (6, 7, 8):  return "summer"
            return "fall"
        merged["season"] = merged["operation_date"].dt.month.map(_to_season)
        group_cols = ["year", "season", "category", "direction", "mandatory"]
    else:
        group_cols = ["year", "category", "direction", "mandatory"]

    return (
        merged.groupby(group_cols)
              .agg(payment_count  =("amount", "count"),
                   total_amount   =("amount", "sum"),
                   avg_amount     =("amount", "mean"),
                   active_streams =("counterparty_key", "nunique"))
              .round(2)
              .reset_index()
              .sort_values(group_cols)
              .reset_index(drop=True)
    )


# =============================== DIAGNOSTICS ================================
def inspect_mandatory(categories_df, classified_df):
    print("=" * 100)
    print("MANDATORY BREAKDOWN")
    print("=" * 100)
    if not categories_df.empty:
        print(
            categories_df.groupby(["category", "mandatory"]).size()
                         .unstack(fill_value=0).to_string()
        )

    mandatory_suppliers = categories_df[
        (categories_df["category"] == "Закупки у поставщиков")
        & (categories_df["mandatory"])
        ][["counterparty_key", "counterparty_name"]].drop_duplicates()

    print("\n" + "=" * 100)
    print("SUPPLIER STREAMS WITH mandatory=True")
    print("=" * 100)
    if mandatory_suppliers.empty:
        print("  (none)")
        return

    merged = classified_df.merge(
        mandatory_suppliers,
        on=["counterparty_key", "counterparty_name"],
        how="inner",
    )
    for (key, name), grp in merged.groupby(
            ["counterparty_key", "counterparty_name"]):
        unique_purposes = (
            grp["payment_purpose"].astype(str).str.lower().str.strip().unique()
        )
        print(f"\n{key}  |  {name}   "
              f"({len(grp)} ops, {len(unique_purposes)} unique purposes)")
        for p in unique_purposes[:5]:
            print(f"    • {p[:120]}")
        if len(unique_purposes) > 5:
            print(f"    … and {len(unique_purposes) - 5} more")


# =============================== PUBLIC API =================================
def analyze_payments(ops: pd.DataFrame,
                     as_of=None,
                     horizon_days: int | None = None,     # ← was 365
                     config: dict | None = None):
    """
    Parameters
    ----------
    ops          : DataFrame of operations.
    as_of        : START of the analysis window (inclusive).
                   Rows with operation_date < as_of are discarded.
                   None = use all available data.
    horizon_days : how far forward from the end of data to build the prognosis.
                   None (default) = until 31 December of the year data ends.
                   Pass an explicit int to override (e.g. 365 for 12 months,
                   0 for no prognosis at all).
    config       : overrides for DEFAULT_CONFIG.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    as_of_ts = pd.Timestamp(as_of).normalize() if as_of is not None else None

    _warn_if_no_calendar(cfg)

    # ---- 1a. per-row parsing ---------------------------------------------
    df = _normalize_basic(ops)

    # ---- 1b. WINDOW GUARD: keep only rows on/after as_of -----------------
    if as_of_ts is not None:
        df = df[(df["operation_date"] >= as_of_ts) | (~df["date_valid"])]
    df = df.reset_index(drop=True)

    if df.empty:
        # Nothing to work with — return the empty shape so callers don't
        # have to special-case the "all data filtered out" path.
        return (pd.DataFrame(columns=STREAM_COLUMNS),
                pd.DataFrame(columns=[
                    "date", "counterparty_key", "counterparty_name",
                    "direction", "category", "cadence", "sub_stream",
                    "stream_id", "mandatory", "mandatory_reason",
                    "predicted_amount", "signed_amount",
                    "confidence", "confidence_label"]),
                df)

    # ---- 1c. cross-row counterparty resolution ---------------------------
    df = _resolve_counterparty_keys(df)

    data_max_date = df.loc[df["date_valid"], "operation_date"].max()

    # ---- 1d. resolve horizon: None = until end of year -------------------
    if horizon_days is None:
        end_of_year = pd.Timestamp(year=data_max_date.year, month=12, day=31)
        horizon_days = max(0, (end_of_year - data_max_date).days)

    # ---- 2. classify ------------------------------------------------------
    classified = _classify(df, cfg)

    # ---- 3. split multi-payment streams -----------------------------------
    classified = _split_multi_per_month(classified, cfg)

    # ---- 4. detection -----------------------------------------------------
    detectable = classified[
        classified["date_valid"]
        & ~classified["category"].isin(NON_STREAM_CATEGORIES)
    ]

    monthly   = _aggregate_monthly(detectable)
    streams   = _detect_and_forecast(monthly, cfg, as_of_ts, data_max_date)
    prognosis = _build_prognosis(streams, data_max_date, horizon_days, cfg)

    all_payments = _annotate_payments(classified, streams, cfg)

    streams.attrs["yearly"]          = yearly_summary(detectable, streams, by_season=False)
    streams.attrs["yearly_seasonal"] = yearly_summary(detectable, streams, by_season=True)
    streams.attrs["all_payments"]    = all_payments
    streams.attrs["prognosis"]       = prognosis
    streams.attrs["row_counts"] = {
        "raw_in_file":        len(all_payments),
        "regular":            int(all_payments["is_regular"].sum()),
        "irregular":          int((~all_payments["is_regular"]).sum()),
        "with_bad_date":      int((~all_payments["date_valid"]).sum()),
        "regular_payment":    int(all_payments["regular_payment"].sum()),
        "mandatory_payment":  int(all_payments["mandatory_payment"].sum()),
        "multi_substreams":   int((streams["sub_stream"] > 0).sum()
                                  if not streams.empty else 0),
    }
    assert (streams.attrs["row_counts"]["regular"]
            + streams.attrs["row_counts"]["irregular"]) == len(all_payments)

    return streams, prognosis, all_payments


# =============================== DEMO =======================================
if __name__ == "__main__":
    # В проде: ops = load_from_db(...); business_cal = load_calendar_from_ml_data()
    CSV = "/home/data/synas/nas_backup/home/vitaliy/hakaton/statements/C123.csv"
    ops = pd.read_csv(CSV, sep=";", dtype=str, keep_default_na=False)

    categories, prognosis, all_payments = analyze_payments(
        ops,
        as_of=None,
        config={
            # business_day_calendar — заменить на данные из ml/data:
            # "business_day_calendar": lambda d: load_workdays(...).contains(d),
        },
    )

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 360)
    pd.set_option("display.max_rows", None)

    print("=" * 110)
    print("REGULAR STREAMS")
    print("=" * 110)
    print(categories[[
        "stream_id", "sub_stream", "counterparty_name", "direction",
        "category", "cadence", "mandatory",
        "predicted_next_date", "predicted_amount",
        "confidence", "confidence_label",
        "date_conf", "amount_conf", "gap_conf",
    ]].to_string(index=False))

    print("\n" + "=" * 110)
    print("MULTI-PAYMENT SPLIT CHECK  (streams where n_subs > 1)")
    print("=" * 110)
    if not categories.empty:
        multi = categories[categories.duplicated(
            ["counterparty_key", "category", "direction"], keep=False)]
        if multi.empty:
            print("  (no multi-payment streams detected)")
        else:
            print(multi[[
                "stream_id", "sub_stream", "counterparty_key",
                "counterparty_name", "category", "direction",
                "active_months", "predicted_amount",
            ]].to_string(index=False))

    print("\n" + "=" * 110)
    print(f"ALL PAYMENTS  ({len(all_payments)} rows; "
          f"{all_payments['is_regular'].sum()} regular, "
          f"{(~all_payments['is_regular']).sum()} irregular)")
    print("=" * 110)

    print("\nROW-COUNT RECONCILIATION")
    for k, v in categories.attrs["row_counts"].items():
        print(f"  {k:22s} {v}")