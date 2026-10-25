"""Базовая очистка выписки: только то, без чего нельзя строить ряд потока.

Владелец модуля — Виталий. Здесь минимальная версия, чтобы прогноз мог работать до готовой
очистки и категоризации. Строки не удаляются, а помечаются флагами — решение принимает панель.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.loaders import INFLOW

# Дубль = совпадение всех содержательных полей (operation_id у дубля свой).
# Проверено на данных: balance_eod дубли не учитывает.
DEDUP_KEY = ["company_id", "operation_date", "amount", "direction",
             "counterparty_inn", "counterparty_name", "payment_purpose"]
OWN_TRANSFER_RE = r"собственн\w* средств"
ERROR_REFUND_RE = r"возврат платежа.*неверно указаны реквизиты"
# заём учредителя и его возврат — финансирование, а не операционный поток; приход займа — реакция
# владельца на нехватку денег (раздел 3 AGENTS.md), учить модель «ждать займа» нельзя
FOUNDER_RE = r"беспроцентн\w* займ"
FOUNDER_NAME_RE = r"учредител"
# выдача банковского кредита/транша: остаётся в потоке, флаг — для признака «живёт на займы»
BANK_LOAN_RE = r"выдача кредита|кредитн\w* лини"


def normalize_purpose(purpose: pd.Series) -> pd.Series:
    return purpose.fillna("").str.lower().str.replace("ё", "е", regex=False)


def clean_operations(ops: pd.DataFrame, refund_window_days: int = 30) -> pd.DataFrame:
    """Добавляет signed, is_duplicate, is_own_transfer, is_founder_financing, is_bank_loan, is_error_refund."""
    df = ops.copy()
    purpose = normalize_purpose(df["payment_purpose"])
    df["signed"] = np.where(df["direction"] == INFLOW, df["amount"], -df["amount"])
    df["is_duplicate"] = df.duplicated(DEDUP_KEY, keep="first")
    df["is_own_transfer"] = purpose.str.contains(OWN_TRANSFER_RE, regex=True)
    name = df["counterparty_name"].fillna("").str.lower()
    df["is_founder_financing"] = (purpose.str.contains(FOUNDER_RE, regex=True)
                                  | name.str.contains(FOUNDER_NAME_RE, regex=True)) & ~df["is_own_transfer"]
    df["is_bank_loan"] = ((df["direction"] == INFLOW) & purpose.str.contains(BANK_LOAN_RE, regex=True)
                          & ~df["is_own_transfer"] & ~df["is_founder_financing"])
    df["is_error_refund"] = _error_refund_pairs(df, purpose, refund_window_days)
    return df


def _error_refund_pairs(df: pd.DataFrame, purpose: pd.Series, window_days: int) -> pd.Series:
    """Помечает возврат ошибочного платежа и сам исходный платёж (та же сумма, раньше, в окне)."""
    flag = pd.Series(False, index=df.index)
    is_refund = (df["direction"] == INFLOW) & purpose.str.contains(ERROR_REFUND_RE, regex=True)
    is_refund &= ~df["is_duplicate"]
    outs = df[(df["direction"] != INFLOW) & ~df["is_duplicate"]]
    candidates = outs.groupby(["company_id", "amount"]).groups
    used: set = set()
    for idx in df.index[is_refund]:
        row = df.loc[idx]
        flag[idx] = True
        pool = candidates.get((row["company_id"], row["amount"]), [])
        lo = row["operation_date"] - pd.Timedelta(days=window_days)
        match = [i for i in pool if i not in used and lo <= df.at[i, "operation_date"] <= row["operation_date"]]
        if match:
            orig = max(match, key=lambda i: df.at[i, "operation_date"])
            used.add(orig)
            flag[orig] = True
    return flag
