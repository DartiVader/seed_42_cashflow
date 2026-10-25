"""Досчёт остатка для операций без остатка банка (ручные, маркетплейсы)."""
import pandas as pd

from service.db import fill_balance


def statement(rows):
    df = pd.DataFrame(rows, columns=["operation_date", "amount", "direction", "balance_eod"])
    df["operation_date"] = pd.to_datetime(df["operation_date"])
    return df


def test_bank_balance_kept_and_gaps_filled_from_it():
    df = statement([
        ("2024-10-01", 50.0, "Списание", None),          # ручная до выписки: назад от первого остатка банка
        ("2024-10-02", 1000.0, "Поступление", 10000.0),
        ("2024-10-03", 200.0, "Списание", 5000.0),        # скачок без операции: остаток банка как есть
        ("2024-10-04", 100.0, "Списание", None),          # ручная после выписки: от последнего остатка банка
        ("2024-10-04", 30.0, "Поступление", None),
    ])
    assert fill_balance(df, opening=777.0).tolist() == [9000.0, 10000.0, 5000.0, 4930.0, 4930.0]


def test_no_bank_balance_uses_opening():
    df = statement([("2024-10-01", 100.0, "Поступление", None), ("2024-10-02", 40.0, "Списание", None)])
    assert fill_balance(df, opening=500.0).tolist() == [600.0, 560.0]
