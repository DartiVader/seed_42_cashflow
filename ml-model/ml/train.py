"""Пайплайн обучения: данные → очистка → панель → backtest моделей → отчёты → финальная модель.

    python -m ml.train                         # все модели
    python -m ml.train --models naive_s5,dow_mean,lgbm --skip-final
    python -m ml.train --final-only            # только финальные lgbm/lgbm_net, калибровка из reports/

Финальные версии: models/lgbm_net-v1 (основная в forecast()) и models/lgbm-v1 (резерв).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ml.data.loaders import load_dataset
from ml.evaluation.backtest import BacktestConfig, run_backtest
from ml.evaluation.calibration import Calibrator, ShortfallCalibrator
from ml.evaluation.gap_metrics import log_amounts, log_summary as log_gap_summary, run as run_gap_metrics
from ml.evaluation.gap_metrics import write_reports as write_gap_reports
from ml.evaluation.metrics import add_balance_paths, residuals, summarize
from ml.evaluation.splits import holdout_companies
from ml.evaluation.ablation import ROWS as ABLATION_ROWS
from ml.evaluation.regular_backtest import VARIANTS, default_workers, labels_at
from ml.forecast.models import MODELS, LgbmConfig
from ml.forecast.panel import PanelConfig, build_panel, data_quality, residual_panel
from ml.pipeline.clean import clean_operations

log = logging.getLogger("ml.train")

FINAL_MODELS = ("lgbm_net", "lgbm")   # сохраняются в реестр models/<имя>-<version>


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.environ.get("ML_DATA_DIR", "cashflow_data/cashflow_dataset_participants"))
    ap.add_argument("--models-dir", default=os.environ.get("ML_MODELS_DIR", "models"))
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--version", default="v1", help="каталог версии: <модель>-<version>")
    ap.add_argument("--skip-final", action="store_true", help="не обучать финальные модели")
    ap.add_argument("--events", default=None, choices=sorted(VARIANTS),
                    help="финальная lgbm_net на нерегулярной части: регулярные категории варианта идут "
                         "событиями (калибровка и ошибки — из reports/ablation/<строка>)")
    ap.add_argument("--final-only", action="store_true",
                    help="без backtest: финальные модели + calibration_<модель>.json из --reports")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    ops, companies = load_dataset(args.data)
    ops = clean_operations(ops)
    log.info("операций: %d, дублей: %d, own_transfer: %d, ошибочных платежей/возвратов: %d",
             len(ops), ops["is_duplicate"].sum(), ops["is_own_transfer"].sum(), ops["is_error_refund"].sum())
    panel_cfg = PanelConfig()
    panel = build_panel(ops, companies, panel_cfg)
    dq = data_quality(panel)
    dq.to_csv(reports / "data_quality.csv", index=False)
    log.info("панель: %d строк, компаний: %d, пропусков: %d, коротких историй: %d (%.1f с)",
             len(panel), panel["company_id"].nunique(), dq["gaps_in_data"].sum(), dq["short_history"].sum(),
             time.perf_counter() - t0)

    if args.events:
        train_with_events(args, ops, companies, panel, panel_cfg)
        log.info("готово за %.1f с", time.perf_counter() - t0)
        return

    names = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = set(names) - set(MODELS)
    if unknown:
        raise SystemExit(f"неизвестные модели: {sorted(unknown)}")
    bt_cfg = BacktestConfig(seed=args.seed)
    final_names = [n for n in names if n in FINAL_MODELS]
    if args.final_only:
        calibrators = {n: {"probability": Calibrator.load(reports / f"calibration_{n}.json"),
                           "shortfall": ShortfallCalibrator.load(reports / f"shortfall_calibration_{n}.json")}
                       for n in final_names if (reports / f"calibration_{n}.json").exists()
                       and (reports / f"shortfall_calibration_{n}.json").exists()}
    else:
        factories = {n: (lambda n=n: MODELS[n](LgbmConfig(seed=args.seed)) if n in FINAL_MODELS else MODELS[n]())
                     for n in names}
        bt = add_balance_paths(run_backtest(panel, companies, factories, bt_cfg))

        comparison = summarize(bt, ["model", "company_set", "period"])
        comparison.to_csv(reports / "model_comparison.csv", index=False)
        summarize(bt, ["model", "company_set", "history"]).to_csv(reports / "model_comparison_by_history.csv",
                                                                  index=False)
        summarize(bt[bt["period"] == "report"], ["model", "industry"]).to_csv(
            reports / "model_comparison_by_industry.csv", index=False)
        residuals(bt).to_parquet(reports / "backtest_residuals.parquet", index=False)
        bt.to_parquet(reports / "backtest_predictions.parquet", index=False)
        _log_comparison(comparison)

        gap_summary, calibrators = write_gap_reports(run_gap_metrics(bt, names), reports)
        log_gap_summary(gap_summary)
        log_amounts(pd.read_csv(reports / "shortfall_metrics.csv"))

    if not args.skip_final:
        holdout = holdout_companies(companies, bt_cfg.holdout_per_industry, args.seed)
        last_day = panel["date"].max()
        for name in final_names:
            final = MODELS[name](LgbmConfig(seed=args.seed))
            final.fit(panel[~panel["company_id"].isin(holdout)], last_day)
            out = Path(args.models_dir) / f"{name}-{args.version}"
            final.save(out)
            if name in calibrators:
                calibrators[name]["probability"].save(out / "calibration.json")
                calibrators[name]["shortfall"].save(out / "shortfall_calibration.json")
            else:
                log.warning("%s: нет калибраторов, вероятность и сумма разрыва будут сырыми", name)
            (out / "training.json").write_text(json.dumps({
                "holdout_companies": holdout, "trained_until": str(last_day.date()),
                "panel_config": asdict(panel_cfg), "backtest_config": asdict(bt_cfg),
            }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            log.info("финальная модель: %s, строк обучения: %d", out, final.n_train_rows)
    log.info("готово за %.1f с", time.perf_counter() - t0)


def train_with_events(args, ops, companies, panel, panel_cfg) -> None:
    """models/lgbm_net-<version>: модель нерегулярной части + events.json + ошибки и калибровка варианта."""
    import shutil

    row = next(r for r, v, m in ABLATION_ROWS if v == args.events and m == "lgbm_net")
    src = Path(args.reports) / "ablation" / row
    bt_cfg = BacktestConfig(seed=args.seed)
    holdout = holdout_companies(companies, bt_cfg.holdout_per_industry, args.seed)
    last_day = panel["date"].max()
    lab = labels_at(ops, last_day, default_workers())
    mask = lab["is_regular"].fillna(False).astype(bool) & lab["category"].isin(VARIANTS[args.events])
    train = residual_panel(build_panel(ops, companies, panel_cfg, regular=mask))
    final = MODELS["lgbm_net"](LgbmConfig(seed=args.seed))
    final.fit(train[~train["company_id"].isin(holdout)], last_day)
    out = Path(args.models_dir) / f"lgbm_net-{args.version}"
    final.save(out)
    for f in ("calibration.json", "shortfall_calibration.json"):
        shutil.copy(src / f, out / f)
    shutil.copy(src / "backtest_residuals.parquet", out / "residuals.parquet")
    (out / "events.json").write_text(json.dumps({
        "variant": args.events, "groups": sorted(VARIANTS[args.events]), "residual_model": row,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "training.json").write_text(json.dumps({
        "holdout_companies": holdout, "trained_until": str(last_day.date()), "events_variant": args.events,
        "regular_ops": int(mask.sum()), "panel_config": asdict(panel_cfg), "backtest_config": asdict(bt_cfg),
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("финальная модель с событиями: %s (%s), регулярных операций: %d, строк обучения: %d",
             out, args.events, int(mask.sum()), final.n_train_rows)


def _log_comparison(comparison: pd.DataFrame) -> None:
    cols = ["model", "company_set", "period", "wape_in", "wape_out", "wape_in_week", "wape_out_week",
            "nmae_bal_d7", "nmae_bal_d30", "mae_bal_d30"]
    rep = comparison[comparison["period"] == "report"][cols]
    log.info("сравнение моделей (period=report):\n%s", rep.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
