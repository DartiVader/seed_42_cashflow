"""Эксперименты задания 8 (подъём точности) поверх продуктовой v2: lgbm_net + обязательные события.

    python -m ml.evaluation.experiments --rows base,features [--rebuild-cache]

Каждая строка — переобучение по всем месячным фолдам, отчёты в reports/exp_<строка>/, общая таблица —
reports/experiments.csv (period=tune — для решения о включении, period=report — итог).
Кэш разметки — reports/regular_cache_exp[_<вариант>]/ (код Влада после правок 24.10).
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from ml.data.loaders import load_dataset
from ml.evaluation.ablation import metrics_row, save_calibrators
from ml.evaluation.backtest import BacktestConfig
from ml.evaluation.gap_metrics import calibrate, evaluate_origins
from ml.evaluation.metrics import add_balance_paths, residuals
from ml.evaluation.regular_backtest import RegularCache, build_cache, default_workers, run_variant
from ml.forecast.models import LgbmConfig, LgbmNet
from ml.forecast.panel import build_panel
from ml.pipeline.clean import clean_operations

log = logging.getLogger("ml.experiments")

# строка → (вариант событий, конфиг модели нерегулярной части)
ROWS = {
    "base": ("mandatory", dict(feature_set="base")),                    # = продуктовая v2
    "features": ("mandatory", dict(feature_set="balance_last_year")),    # 8.1 + 8.2
    "last_year": ("mandatory", dict(feature_set="last_year")),          # 8.2 без признаков остатка
    "prob": ("mandatory_prob", dict(feature_set="base")),               # 8.3
    "prob_features": ("mandatory_prob", dict(feature_set="balance_last_year")),
    # 8.5: восстановленный ряд — переносы обязательных платежей из-за нехватки денег на нормальных датах;
    # признаки base: остаток (8.1) не берём по условию, last_year отдельно не проверяли
    "v2_cf": ("mandatory_cf", dict(feature_set="base")),
}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="cashflow_data/cashflow_dataset_participants")
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--rows", default=",".join(ROWS))
    ap.add_argument("--rebuild-cache", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("categorizer").setLevel(logging.WARNING)
    reports = Path(args.reports)
    t0 = time.perf_counter()

    ops, companies = load_dataset(args.data)
    ops = clean_operations(ops)
    panel = build_panel(ops, companies)
    cfg = BacktestConfig()
    caches: dict[str, RegularCache] = {}

    def cache_for(variant: str) -> RegularCache:
        if variant not in caches:
            d = reports / ("regular_cache_exp" if variant == "mandatory" else f"regular_cache_exp_{variant}")
            if args.rebuild_cache or not (d / f"rows_{variant}.parquet").exists():
                build_cache(ops, companies, panel, cfg, workers=default_workers(), variants=(variant,)).save(d)
            caches[variant] = RegularCache.load(d)
        return caches[variant]

    table_path = reports / "experiments.csv"
    table = pd.read_csv(table_path) if table_path.exists() else pd.DataFrame()
    for row in args.rows.split(","):
        d = reports / f"exp_{row}"
        d.mkdir(parents=True, exist_ok=True)
        variant, params = ROWS[row]
        factory = lambda p=params: LgbmNet(LgbmConfig(seed=cfg.seed, **p))
        bt = add_balance_paths(run_variant(variant, factory, ops, companies, panel, cache_for(variant), cfg, name=row))
        bt.to_parquet(d / "backtest_predictions.parquet", index=False)
        residuals(bt.assign(model=row)).to_parquet(d / "backtest_residuals.parquet", index=False)
        save_calibrators(bt, row, d)
        res, _ = calibrate(evaluate_origins(bt.assign(model=row), row))
        m = pd.concat([metrics_row(bt, row, period, res) for period in ("tune", "report")], ignore_index=True)
        m.to_csv(d / "metrics.csv", index=False)
        if not table.empty:
            table = table[table["row"] != row]
        table = pd.concat([table, m], ignore_index=True)
        table.to_csv(table_path, index=False)
        log.info("строка %s готова, %.0f с", row, time.perf_counter() - t0)
    cols = ["row", "period", "company_set", "nmae_bal_d7", "nmae_bal_d30", "strict_recall", "strict_precision",
            "counterfactual_recall", "counterfactual_precision", "counterfactual_brier_cal",
            "sf_total_mae_rub", "sf_total_in_range_p10_p90", "coverage_p10_p90"]
    log.info("эксперименты:\n%s", table[[c for c in cols if c in table]].to_string(
        index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
