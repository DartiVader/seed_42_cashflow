"""ExponentialSmoothing по каждой компании (statsmodels, сезонность 5 рабочих дней)."""
from __future__ import annotations

import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.forecast.features import FLOWS
from ml.forecast.models.base import RowModel, first_available


@dataclass(frozen=True)
class EtsConfig:
    window: int = 250          # рабочих дней истории для подгонки
    min_obs: int = 20
    workers: int = max(1, (os.cpu_count() or 2) - 1)


class EtsFlow(RowModel):
    name = "ets"

    def __init__(self, config: EtsConfig = EtsConfig()):
        self.config = config

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        horizon = int(rows["h"].max())
        tasks = []
        for cid, g in rows.groupby("company_id", sort=False):
            series = panel.loc[panel["company_id"] == cid]
            ys = [series[f"y_{f}"].where(~series["gap_in_data"]).to_numpy() for f in FLOWS]
            ends = g.drop_duplicates("as_of")["hist_len"].to_numpy()
            tasks.append((ys, ends, horizon, self.config))
        with ProcessPoolExecutor(max_workers=self.config.workers) as pool:
            results = list(pool.map(_company_forecasts, tasks))

        preds = {f: np.full(len(rows), np.nan) for f in FLOWS}
        for (cid, g), res in zip(rows.groupby("company_id", sort=False), results):
            pos = {a: i for i, a in enumerate(g.drop_duplicates("as_of")["as_of"])}
            o = g["as_of"].map(pos).to_numpy()
            h = g["h"].to_numpy() - 1
            for j, f in enumerate(FLOWS):
                preds[f][rows.index.get_indexer(g.index)] = res[j][o, h]
        fallback = {f: rows[f"raw_{f}_mean20"].to_numpy() for f in FLOWS}
        return tuple(first_available(preds[f], fallback[f]) for f in FLOWS)


def _company_forecasts(task) -> list[np.ndarray]:
    ys, ends, horizon, cfg = task
    out = []
    for y in ys:
        res = np.full((len(ends), horizon), np.nan)
        for i, end in enumerate(ends):
            res[i] = _ets_forecast(y[max(0, end - cfg.window):end], horizon, cfg.min_obs)
        out.append(res)
    return out


def _ets_forecast(y: np.ndarray, horizon: int, min_obs: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    y = pd.Series(y).interpolate(limit_direction="both").to_numpy()
    if np.isnan(y).all() or np.sum(~np.isnan(y)) < min_obs or np.nanstd(y) == 0:
        return np.full(horizon, np.nan)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(y, trend=None, seasonal="add", seasonal_periods=5,
                                       initialization_method="estimated").fit()
            return np.clip(fit.forecast(horizon), 0, None)
    except (ValueError, np.linalg.LinAlgError):
        return np.full(horizon, np.nan)
