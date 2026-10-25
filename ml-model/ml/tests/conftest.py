"""Синтетические выписки с согласованным остатком для тестов."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.data.calendar import working_days
from ml.data.loaders import INFLOW, OUTFLOW


def make_ops(company_ids=("C001", "C002", "C003"), start="2025-01-09", n_days=300,
             start_balance=500_000.0, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = working_days(start, "2026-12-31")[:n_days]
    rows = []
    for cid in company_ids:
        for i, d in enumerate(days):
            dow_k = 1.6 if d.day_of_week == 0 else 1.0
            rows.append((cid, d, round(float(rng.lognormal(10.5, 0.3)) * dow_k, 2), INFLOW, "0011111111",
                         "ПАО «Банк»", "Зачисление средств по операциям эквайринга"))
            if i % 5 == 2:
                rows.append((cid, d, round(float(rng.uniform(80_000, 120_000)), 2), OUTFLOW, "0022222222",
                             "ООО «Поставщик-1»", "Оплата по счету за товар"))
            if d.day in (10, 25):
                rows.append((cid, d, 60_000.0, OUTFLOW, None, "Сотрудник", "Заработная плата"))
    ops = pd.DataFrame(rows, columns=["company_id", "operation_date", "amount", "direction",
                                      "counterparty_inn", "counterparty_name", "payment_purpose"])
    ops["operation_id"] = [f"{c}-{i:06d}" for i, c in enumerate(ops["company_id"])]
    return rebalance(ops, start_balance)


def rebalance(ops: pd.DataFrame, start_balance: float = 500_000.0) -> pd.DataFrame:
    """Пересчитать balance_eod так, чтобы остаток сходился с операциями."""
    ops = ops.sort_values(["company_id", "operation_date", "operation_id"]).reset_index(drop=True)
    signed = np.where(ops["direction"] == INFLOW, ops["amount"], -ops["amount"])
    day = ops.assign(s=signed).groupby(["company_id", "operation_date"])["s"].sum()
    bal = start_balance + day.groupby(level=0).cumsum()
    ops["balance_eod"] = bal.reindex(pd.MultiIndex.from_frame(ops[["company_id", "operation_date"]])).to_numpy()
    return ops


def make_companies(ops: pd.DataFrame) -> pd.DataFrame:
    g = ops.groupby("company_id")["operation_date"]
    ids = sorted(ops["company_id"].unique())
    return pd.DataFrame({
        "company_id": ids, "company_name": ids, "company_inn": "0012345678", "legal_form": "ООО",
        "industry": ["Общепит" if i % 2 == 0 else "Опт" for i in range(len(ids))],
        "first_operation_date": g.min().reindex(ids).to_numpy(),
        "last_operation_date": g.max().reindex(ids).to_numpy(),
        "operations_count": g.size().reindex(ids).to_numpy(),
    })


@pytest.fixture
def synthetic():
    ops = make_ops()
    return ops, make_companies(ops)


def no_timing(d: dict) -> dict:
    """Ответ forecast() без времени шагов в trace: оно меняется от вызова к вызову, остальное детерминировано."""
    return {**d, "trace": [{k: v for k, v in s.items() if k != "ms"} for s in d.get("trace", [])]}
