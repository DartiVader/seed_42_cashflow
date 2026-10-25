"""Общий интерфейс моделей нерегулярного потока."""
from __future__ import annotations

from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from ml.data.calendar import last_working_day
from ml.forecast.features import ID_COLS, make_rows

PRED_COLS = [*ID_COLS, "in_hat", "out_hat"]


class FlowModel(Protocol):
    name: str

    def fit(self, panel: pd.DataFrame, as_of: date) -> None: ...

    def predict(self, panel: pd.DataFrame, as_of: date, horizon: int) -> pd.DataFrame: ...


class RowModel:
    """База: predict по одному as_of для всех компаний и пакетный predict_rows для backtest.

    predict_rows получает готовые строки признаков (make_rows) — так backtest строит их
    один раз на фолд для всех моделей. Возвращает (in_hat, out_hat) в рублях, ≥ 0.
    """
    name = "base"

    def fit(self, panel: pd.DataFrame, as_of: date) -> None:
        return None

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def predict(self, panel: pd.DataFrame, as_of: date, horizon: int) -> pd.DataFrame:
        day = last_working_day(as_of)
        origins = panel.loc[panel["date"] == day, ["company_id"]].assign(as_of=day)
        rows = make_rows(panel, origins, horizon)
        in_hat, out_hat = self.predict_rows(rows, panel)
        return rows[ID_COLS].assign(in_hat=in_hat, out_hat=out_hat)


def first_available(*arrays: np.ndarray) -> np.ndarray:
    """Поэлементно первое не-NaN значение, иначе 0."""
    out = np.full(len(arrays[0]), np.nan)
    for a in arrays:
        out = np.where(np.isnan(out), a, out)
    return np.clip(np.nan_to_num(out), 0, None)
