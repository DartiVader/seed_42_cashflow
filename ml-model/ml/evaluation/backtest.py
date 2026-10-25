"""Rolling-origin backtest: месячные фолды с переобучением, недельные as_of, холдаут компаний."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from ml.evaluation.splits import holdout_companies, month_cutoffs
from ml.forecast.features import ID_COLS, attach_targets, day_features, make_rows, weekly_origins
from ml.forecast.models.base import RowModel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    horizon: int = 23                  # рабочих дней ≈ 30 календарных
    first_cutoff: str = "2025-09-30"   # первый фолд учится на годе истории
    last_origin: str = "2026-08-31"    # конец данных − 30 дней
    report_from: str = "2026-02-01"    # раньше — фолды для подбора, позже — для отчёта
    min_history: int = 20
    holdout_per_industry: int = 1
    seed: int = 42


def run_backtest(panel: pd.DataFrame, companies: pd.DataFrame,
                 factories: dict[str, Callable[[], RowModel]],
                 cfg: BacktestConfig = BacktestConfig()) -> pd.DataFrame:
    """Возвращает длинную таблицу прогнозов всех моделей с фактом (по строке на model × origin × h)."""
    holdout = holdout_companies(companies, cfg.holdout_per_industry, cfg.seed)
    train_panel = panel[~panel["company_id"].isin(holdout)]
    log.info("holdout: %d компаний, обучение: %d", len(holdout), train_panel["company_id"].nunique())

    feats = day_features(panel)
    cutoffs = month_cutoffs(cfg.first_cutoff, cfg.last_origin)
    bounds = cutoffs[1:] + [pd.Timestamp(cfg.last_origin)]
    origins = weekly_origins(panel, start=cutoffs[0], end=cfg.last_origin, min_history=cfg.min_history)

    parts = []
    for cutoff, upper in zip(cutoffs, bounds):
        fold = origins[(origins["as_of"] > cutoff) & (origins["as_of"] <= upper)]
        if fold.empty:
            continue
        rows = make_rows(panel, fold, cfg.horizon, day_feats=feats)
        for name, factory in factories.items():
            t0 = time.perf_counter()
            model = factory()
            model.fit(train_panel, cutoff)
            # out-of-time: модель фолда видела только целевые даты ≤ cutoff, оцениваем as_of > cutoff
            trained_until = getattr(model, "trained_until", None)
            assert trained_until is None or pd.Timestamp(trained_until) <= cutoff < fold["as_of"].min()
            in_hat, out_hat = model.predict_rows(rows, panel)
            parts.append(rows[ID_COLS + ["scale", "industry", "hist_len"]].assign(
                model=name, cutoff=cutoff, in_hat=in_hat, out_hat=out_hat))
            log.info("фолд %s модель %s: origins=%d, %.1f с", cutoff.date(), name, len(fold),
                     time.perf_counter() - t0)

    preds = pd.concat(parts, ignore_index=True)
    out = attach_targets(preds, panel)
    # new_dates — компании из обучения, но даты после cutoff; new_companies — холдаут, не виденный моделью
    out["company_set"] = out["company_id"].isin(holdout).map({True: "new_companies", False: "new_dates"})
    out["period"] = (out["as_of"] >= pd.Timestamp(cfg.report_from)).map({True: "report", False: "tune"})
    out["history"] = pd.cut(out["hist_len"], [0, 59, 125, 10**6], labels=["<60", "60-125", "126+"])
    return out
