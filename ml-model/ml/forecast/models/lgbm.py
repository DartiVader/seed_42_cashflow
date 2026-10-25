"""Глобальная LightGBM по всем компаниям, direct-стратегия (h — признак), цели y/scale.

Цель L2, а не L1/Huber: остаток — накопленная сумма потока, ему нужна несмещённая
оценка среднего. Медиана у редких B2B-поступлений ≈ 0, и остаток систематически уезжал бы вниз.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.forecast.features import CAT_FEATURES, FLOWS, attach_targets, feature_columns, make_rows, weekly_origins
from ml.forecast.models.base import RowModel


def _default_params() -> dict:
    return dict(
        objective="regression", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
        deterministic=True, force_row_wise=True, num_threads=4, verbose=-1,
    )


@dataclass
class LgbmConfig:
    horizon: int = 23
    num_boost_round: int = 500
    params: dict = field(default_factory=_default_params)
    min_history: int = 20
    target_clip: float = 20.0          # y/scale; разовые уже убраны, это защита от остатков выбросов
    low_balance_weight: float = 0.3    # вес дней с остатком < scale: там владелец переносит платежи
    feature_set: str = "base"          # ml.forecast.features.FEATURE_SETS (эксперименты 8.x)
    seed: int = 42


class LgbmFlow(RowModel):
    name = "lgbm"

    def __init__(self, config: LgbmConfig | None = None):
        self.config = config or LgbmConfig()
        self.boosters: dict[str, lgb.Booster] = {}
        self.categories: dict[str, list[str]] = {}
        self.trained_until: str | None = None
        self.n_train_rows = 0

    def fit(self, panel: pd.DataFrame, as_of: date) -> None:
        cfg = self.config
        as_of = pd.Timestamp(as_of)
        origins = weekly_origins(panel, end=as_of, min_history=cfg.min_history)
        rows = attach_targets(make_rows(panel, origins, cfg.horizon), panel)
        # embargo: учимся только на целевых днях ≤ as_of
        rows = rows[(rows["target_date"] <= as_of) & rows["target_valid"]]
        if rows.empty:
            raise ValueError("нет обучающих строк до as_of")
        self.categories = {c: sorted(panel[c].dropna().unique().tolist()) for c in CAT_FEATURES}
        X = self._matrix(rows)
        weight = np.where(rows["bal_true"] < rows["scale"], cfg.low_balance_weight, 1.0)
        params = {**cfg.params, "seed": cfg.seed}
        for f in FLOWS:
            y = rows[f"y_{f}_norm"].clip(upper=cfg.target_clip).to_numpy()
            ds = lgb.Dataset(X, y, weight=weight, categorical_feature=CAT_FEATURES, free_raw_data=True)
            self.boosters[f] = lgb.train(params, ds, num_boost_round=cfg.num_boost_round)
        self.trained_until = str(as_of.date())
        self.n_train_rows = len(rows)

    def predict_rows(self, rows: pd.DataFrame, panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        X = self._matrix(rows)
        scale = rows["scale"].to_numpy()
        return tuple(np.clip(self.boosters[f].predict(X), 0, None) * scale for f in FLOWS)

    def _matrix(self, rows: pd.DataFrame) -> pd.DataFrame:
        X = rows[feature_columns(self.config.feature_set)].copy()
        for c in CAT_FEATURES:
            v = X[c].astype(str)
            # значение не из обучения (новая отрасль, «неизвестно») — пропуск, как и в LightGBM
            X[c] = pd.Categorical(v.where(v.isin(self.categories[c])), categories=self.categories[c])
        return X

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        for f, b in self.boosters.items():
            b.save_model(str(path / f"booster_{f}.txt"))
        meta = {"name": self.name, "config": asdict(self.config), "categories": self.categories,
                "features": feature_columns(self.config.feature_set), "trained_until": self.trained_until,
                "n_train_rows": self.n_train_rows}
        (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LgbmFlow":
        path = Path(path)
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        if meta["name"] != cls.name:
            raise ValueError(f"в {path} модель {meta['name']}, а загружается {cls.name}")
        if meta["features"] != feature_columns(meta["config"].get("feature_set", "base")):
            raise ValueError("набор признаков модели не совпадает с текущим кодом")
        m = cls(LgbmConfig(**meta["config"]))
        m.categories = meta["categories"]
        m.trained_until = meta["trained_until"]
        m.n_train_rows = meta["n_train_rows"]
        m.boosters = {f: lgb.Booster(model_file=str(path / f"booster_{f}.txt")) for f in FLOWS}
        return m
