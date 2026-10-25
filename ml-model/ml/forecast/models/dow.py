"""Среднее по дню недели за последние 8 недель."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.forecast.features import FLOWS
from ml.forecast.models.base import RowModel, first_available


class DowMean(RowModel):
    name = "dow_mean"

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        out = [first_available(rows[f"raw_{f}_dow_target"].to_numpy(), rows[f"raw_{f}_mean20"].to_numpy())
               for f in FLOWS]
        return out[0], out[1]
