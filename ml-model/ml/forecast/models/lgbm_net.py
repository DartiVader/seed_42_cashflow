"""LightGBM с прямым прогнозом изменения остатка: цель Σ_{k≤h}(y_in − y_out) / (scale · √h).

Известное ограничение: у компаний с устойчивым оттоком (нет выручки, платит учредитель) прогноз на h=1–3
завышает падение, на h=21 занижает — константа дерева даёт поток ∝ √h. Цель /h с весом h это чинит, но
nmae_bal_d30 хуже (reports/exp_net_linear), поэтому не принята. Признаки founder_in_60/loan_in_60/founder_share_60
тоже не помогли (reports/exp_founder): у lgbm d30 хуже на 0,11, у C103 падение ещё глубже.

Учится ровно той величине, по которой оцениваем остаток. Дневные in/out берутся из обычной
lgbm и подтягиваются так, чтобы их накопленная разница на каждом h совпала с прогнозом net:
линия остатка и дневные столбики на графике не расходятся.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.forecast.features import CAT_FEATURES, attach_targets, make_rows, weekly_origins
from ml.forecast.models.lgbm import LgbmConfig, LgbmFlow

NET_CLIP = 15.0   # |накопленный поток| / √h в дневных оборотах


class LgbmNet(LgbmFlow):
    name = "lgbm_net"

    def __init__(self, config: LgbmConfig | None = None):
        super().__init__(config)
        self.net_booster: lgb.Booster | None = None

    def fit(self, panel: pd.DataFrame, as_of: date) -> None:
        super().fit(panel, as_of)
        cfg = self.config
        as_of = pd.Timestamp(as_of)
        origins = weekly_origins(panel, end=as_of, min_history=cfg.min_history)
        rows = attach_targets(make_rows(panel, origins, cfg.horizon), panel)
        rows = rows[(rows["target_date"] <= as_of) & rows["y_in"].notna() & ~rows["gap_between"]]
        # делим на √h: разброс накопленного потока растёт с горизонтом, иначе L2 учит только дальние h
        y = (rows["dflow_true"] / rows["scale"] / np.sqrt(rows["h"])).clip(-NET_CLIP, NET_CLIP).to_numpy()
        weight = np.where(rows["bal_true"] < rows["scale"], cfg.low_balance_weight, 1.0)
        ds = lgb.Dataset(self._matrix(rows), y, weight=weight, categorical_feature=CAT_FEATURES)
        self.net_booster = lgb.train({**cfg.params, "seed": cfg.seed}, ds, num_boost_round=cfg.num_boost_round)

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        in_hat, out_hat = super().predict_rows(rows, panel)
        cum_net = self.net_booster.predict(self._matrix(rows)) * np.sqrt(rows["h"].to_numpy()) * rows["scale"].to_numpy()
        return reconcile(rows, in_hat, out_hat, cum_net)

    def save(self, path: str | Path) -> None:
        super().save(path)
        self.net_booster.save_model(str(Path(path) / "booster_net.txt"))

    @classmethod
    def load(cls, path: str | Path) -> "LgbmNet":
        m = super().load(path)
        m.net_booster = lgb.Booster(model_file=str(Path(path) / "booster_net.txt"))
        return m


def reconcile(rows: pd.DataFrame, in_hat: np.ndarray, out_hat: np.ndarray,
              cum_net: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Минимальная правка дневных in/out (≥ 0), чтобы Σ_{k≤h}(in − out) = cum_net[h] для каждого h."""
    keys = [rows["company_id"].to_numpy(), rows["as_of"].to_numpy()]
    daily_net = pd.Series(cum_net).groupby(keys).diff().fillna(pd.Series(cum_net)).to_numpy()
    adj = daily_net - (in_hat - out_hat)
    return in_hat + np.clip(adj, 0, None), out_hat + np.clip(-adj, 0, None)

