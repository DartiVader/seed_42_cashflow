"""Нулевой поток: «остаток не изменится». Нижняя планка для любой модели."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.forecast.models.base import RowModel


class ZeroFlow(RowModel):
    name = "zero"

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        zeros = np.zeros(len(rows))
        return zeros, zeros.copy()
