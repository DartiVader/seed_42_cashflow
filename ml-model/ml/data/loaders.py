"""Чтение выписок и справочника компаний. Только формат и типы, без логики модели."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# ИНН всегда строкой: вымышленные ИНН начинаются с «00»
READ_KW = dict(sep=";", encoding="utf-8-sig")
OPS_DTYPES = {"counterparty_inn": str, "inn": str}
COMPANY_DTYPES = {"company_inn": str, "inn": str}

OPS_COLUMNS = [
    "company_id", "operation_id", "operation_date", "amount", "direction",
    "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod",
]
INFLOW = "Поступление"
OUTFLOW = "Списание"


def load_operations(path: str | Path) -> pd.DataFrame:
    ops = pd.read_csv(path, **READ_KW, dtype=OPS_DTYPES, parse_dates=["operation_date"])
    missing = set(OPS_COLUMNS) - set(ops.columns)
    if missing:
        raise ValueError(f"в выписке нет колонок: {sorted(missing)}")
    bad = ~ops["direction"].isin([INFLOW, OUTFLOW])
    if bad.any():
        raise ValueError(f"неизвестное направление в {int(bad.sum())} операциях")
    return ops


def load_companies(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, **READ_KW, dtype=COMPANY_DTYPES,
                       parse_dates=["first_operation_date", "last_operation_date"])


def load_dataset(root: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = Path(root)
    return load_operations(root / "all_operations.csv"), load_companies(root / "companies.csv")
