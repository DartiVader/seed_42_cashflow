"""Сезонный наивный: значение того же дня недели неделю назад (5 рабочих дней)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.forecast.features import FLOWS
from ml.forecast.models.base import RowModel, first_available


class SeasonalNaive(RowModel):
    name = "naive_s5"

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        h = rows["h"].to_numpy()
        # целевой день − 5·ceil(h/5) = as_of − m, то есть lag_{m+1}
        m = (5 * np.ceil(h / 5) - h).astype(int)
        idx = np.arange(len(rows))
        out = []
        for f in FLOWS:
            lags = rows[[f"raw_{f}_lag{k}" for k in range(1, 6)]].to_numpy()
            out.append(first_available(lags[idx, m], rows[f"raw_{f}_mean20"].to_numpy()))
        return out[0], out[1]
