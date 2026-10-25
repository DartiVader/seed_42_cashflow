"""Проверка выписки, загруженной через сайт: колонки, типы, даты. Ошибка — InvalidStatementError (HTTP 400)."""
from __future__ import annotations

import pandas as pd

from ml.data.loaders import INFLOW, OPS_COLUMNS, OUTFLOW
from ml.forecast.contracts import InvalidStatementError

REQUIRED = [c for c in OPS_COLUMNS if c not in ("company_id", "operation_id")]
UNKNOWN_INDUSTRY = "неизвестно"


def validate_statement(ops: pd.DataFrame, company_id: str, as_of: pd.Timestamp) -> pd.DataFrame:
    """Выписка одной компании в формате датасета; операции после as_of отрезаются."""
    if not isinstance(ops, pd.DataFrame) or ops.empty:
        raise InvalidStatementError("Выписка пустая — загрузите файл с операциями.")
    missing = [c for c in REQUIRED if c not in ops.columns]
    if missing:
        raise InvalidStatementError(f"В выписке не хватает колонок: {', '.join(missing)}.")
    df = ops.copy()
    if "company_id" in df.columns:
        other = df["company_id"].dropna().astype(str).unique()
        if len(other) and set(other) != {company_id}:
            raise InvalidStatementError("В выписке операции другой компании — загрузите выписку только своего счёта.")
    df["company_id"] = company_id
    if "operation_id" not in df.columns:
        df["operation_id"] = [f"{company_id}-u{i:06d}" for i in range(len(df))]

    dates = pd.to_datetime(df["operation_date"], errors="coerce", format="mixed", dayfirst=False)
    bad = int(dates.isna().sum())
    if bad:
        raise InvalidStatementError(f"Не удалось прочитать дату в {bad} операциях — нужен формат ГГГГ-ММ-ДД.")
    df["operation_date"] = dates.dt.normalize()
    for col in ("amount", "balance_eod"):
        num = pd.to_numeric(df[col], errors="coerce")
        if num.isna().any():
            raise InvalidStatementError(f"Колонка {col}: {int(num.isna().sum())} значений не число.")
        df[col] = num.astype(float)
    if (df["amount"] <= 0).any():
        raise InvalidStatementError("Сумма операции должна быть больше нуля; направление — в колонке direction.")
    bad = ~df["direction"].isin([INFLOW, OUTFLOW])
    if bad.any():
        raise InvalidStatementError(f"Направление операции — «{INFLOW}» или «{OUTFLOW}»; "
                                    f"не распознано в {int(bad.sum())} операциях.")
    # ИНН строкой: число теряет ведущие нули («0012…» → 12…)
    if pd.api.types.is_numeric_dtype(df["counterparty_inn"]):
        raise InvalidStatementError("ИНН контрагента должен быть строкой — числом теряются ведущие нули.")
    df["counterparty_inn"] = df["counterparty_inn"].astype("string").str.strip().replace("", pd.NA)
    for col in ("counterparty_name", "payment_purpose"):
        df[col] = df[col].astype("string")

    df = df[df["operation_date"] <= as_of]        # будущее (> as_of) отрезаем
    if df.empty:
        raise InvalidStatementError(f"В выписке нет операций до {as_of:%d.%m.%Y}.")
    return df.sort_values(["operation_date", "operation_id"]).reset_index(drop=True)


def company_row(company_id: str, companies: pd.DataFrame | None, industry: str | None) -> tuple[pd.DataFrame, bool]:
    """Строка справочника для build_panel и флаг «отрасль известна»."""
    if companies is not None and (companies["company_id"] == company_id).any():
        return companies[companies["company_id"] == company_id], True
    known = bool(industry)
    return pd.DataFrame({"company_id": [company_id], "industry": [industry or UNKNOWN_INDUSTRY],
                         "legal_form": [None]}), known
