"""Абляция регулярных событий (reports/ablation.csv): lgbm_net, переобучение для каждой строки.

    python -m ml.evaluation.ablation [--rebuild-cache]

Строки: 1) без событий — lgbm_net из основного backtest (reports/backtest_predictions.parquet);
2) + налоги; 3) + налоги + зарплата; 4) + всё обязательное; 5) + регулярные поступления клиентов;
zero + все события — нерегулярная часть = 0.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from ml.data.loaders import load_dataset
from ml.evaluation.backtest import BacktestConfig
from ml.evaluation.gap_metrics import CALIBRATION_LABEL, calibrate, evaluate_origins, summarize_amounts, summarize_gaps
from ml.evaluation.metrics import add_balance_paths, residuals, summarize
from ml.evaluation.regular_backtest import RegularCache, build_cache, default_workers, run_variant
from ml.forecast.models import LgbmConfig, LgbmNet
from ml.forecast.panel import build_panel
from ml.pipeline.clean import clean_operations

log = logging.getLogger("ml.ablation")

ROWS = [  # (строка, вариант событий, модель нерегулярной части)
    ("1_no_events", None, "lgbm_net"),
    ("2_tax", "tax", "lgbm_net"),
    ("3_tax_salary", "tax_salary", "lgbm_net"),
    ("4_mandatory", "mandatory", "lgbm_net"),
    ("5_mandatory_revenue", "mandatory_revenue", "lgbm_net"),
    ("zero_all_events", "mandatory_revenue", "zero"),
]
BY = ["company_set"]


def metrics_row(bt: pd.DataFrame, row: str, period: str = "report", res: pd.DataFrame | None = None) -> pd.DataFrame:
    """Одна строка на company_set: остаток 7/30, разрывы по двум меткам, суммы, покрытие коридора.
    period=tune — для решения о включении (калиброванные Brier/суммы там in-sample), report — итог."""
    bal = summarize(bt, ["company_set", "period"])
    bal = bal[bal["period"] == period].set_index("company_set")[["nmae_bal_d7", "nmae_bal_d30"]]
    if res is None:
        res, _ = calibrate(evaluate_origins(bt.assign(model=row), row))
    rep = res[(res["period"] == period) & (res["start"] == "positive")]
    out = bal.copy()
    gaps = summarize_gaps(rep, BY)
    gaps_cal = summarize_gaps(rep, BY, prob_col="probability_cal")
    for label in ("strict", "counterfactual"):
        g = gaps[gaps["label"] == label].set_index("company_set")
        gc = gaps_cal[gaps_cal["label"] == label].set_index("company_set")
        out[f"{label}_true_gaps"] = g["true_gaps"]
        out[f"{label}_precision"] = g["precision"]
        out[f"{label}_recall"] = g["recall"]
        out[f"{label}_brier_cal"] = gc["brier"]
    out["coverage_p10_p90"] = gaps[gaps["label"] == "strict"].set_index("company_set")["coverage_p10_p90"]
    am = summarize_amounts(rep, BY)
    am = am[(am["label"] == CALIBRATION_LABEL) & (am["variant"] == "cal")]
    for kind, g in am.groupby("amount"):
        g = g.set_index("company_set")
        for col in ("mae_rub", "median_rel_err", "within_30pct", "in_range_p10_p90"):
            out[f"sf_{kind}_{col}"] = g[col]
    return out.reset_index().assign(row=row, period=period)


def save_calibrators(bt: pd.DataFrame, row: str, out: Path) -> None:
    """Калибровка вероятности и суммы для варианта (tune-фолды), как в gap_metrics.write_reports."""
    _, cals = calibrate(evaluate_origins(bt.assign(model=row), row))
    cals[row]["probability"].save(out / "calibration.json")
    cals[row]["shortfall"].save(out / "shortfall_calibration.json")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="cashflow_data/cashflow_dataset_participants")
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--rebuild-cache", action="store_true")
    ap.add_argument("--rows", default=",".join(r for r, _, _ in ROWS))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("categorizer").setLevel(logging.WARNING)
    reports = Path(args.reports)
    out_dir = reports / "ablation"
    cache_dir = reports / "regular_cache"
    t0 = time.perf_counter()

    ops, companies = load_dataset(args.data)
    ops = clean_operations(ops)
    panel = build_panel(ops, companies)
    cfg = BacktestConfig()
    if args.rebuild_cache or not (cache_dir / "events.parquet").exists():
        build_cache(ops, companies, panel, cfg, workers=default_workers()).save(cache_dir)
    cache = RegularCache.load(cache_dir)

    wanted = set(args.rows.split(","))
    table = []
    for row, variant, model in ROWS:
        if row not in wanted:
            continue
        d = out_dir / row
        d.mkdir(parents=True, exist_ok=True)
        if variant is None:
            bt = pd.read_parquet(reports / "backtest_predictions.parquet", filters=[("model", "==", model)])
        else:
            factory = (lambda: LgbmNet(LgbmConfig(seed=cfg.seed))) if model == "lgbm_net" else None
            bt = add_balance_paths(run_variant(variant, factory, ops, companies, panel, cache, cfg, name=row))
            bt.to_parquet(d / "backtest_predictions.parquet", index=False)
        residuals(bt.assign(model=row)).to_parquet(d / "backtest_residuals.parquet", index=False)
        save_calibrators(bt, row, d)
        m = metrics_row(bt, row)
        m.to_csv(d / "metrics.csv", index=False)
        table.append(m)
        log.info("строка %s готова, %.0f с", row, time.perf_counter() - t0)
    abl = pd.concat(table, ignore_index=True)
    abl = abl[["row"] + [c for c in abl.columns if c != "row"]]
    if set(wanted) >= {r for r, _, _ in ROWS}:
        abl.to_csv(reports / "ablation.csv", index=False)
    log.info("абляция:\n%s", abl.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
