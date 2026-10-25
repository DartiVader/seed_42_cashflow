"""Эксперимент 8.0: оракулы — потолок метрик v2, если одна часть прогноза идеальна.

    python -m ml.evaluation.oracle [--run exp_base]

Берём прогнозы v2 из backtest (reports/<run>/backtest_predictions.parquet, строка base) и раскладываем
in_hat/out_hat на нерегулярную часть (LightGBM) и ожидаемые события (amount × confidence, кэш
reports/regular_cache_exp). Затем по одной части подменяем фактом из будущего:

  O1 — нерегулярная часть = факт: y − регулярные обязательные операции; события — как в прогнозе;
  O2 — события = факт: регулярные обязательные операции по фактическим датам и суммам;
  O3 — даты поступлений нерегулярной части = факт: сумма поступлений модели за горизонт сохраняется,
       по дням раскладывается как фактические поступления (если их нет — как у модели).
       В backtest-МК нет отдельной модели задержек: неопределённость дат сидит в LightGBM и пуле ошибок,
       поэтому «без случайных задержек» = точные даты при суммах модели.

Регулярность в будущем — по разметке кода Влада на последнюю дату данных (оракул, это утечка, так и задумано).
Пул ошибок МК строится из ошибок самого варианта с целевой датой ≤ cutoff, как в gap_metrics.
Только для анализа, в продукт не идёт. Выход: reports/oracle.csv, reports/exp_oracle_<O>/.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.loaders import load_dataset
from ml.evaluation.ablation import metrics_row
from ml.evaluation.gap_metrics import calibrate, evaluate_origins
from ml.evaluation.metrics import add_balance_paths
from ml.evaluation.regular_backtest import VARIANTS, RegularCache, add_events, default_workers, labels_at
from ml.forecast.panel import build_panel
from ml.pipeline import regular as reg
from ml.pipeline.clean import clean_operations

log = logging.getLogger("ml.oracle")

ORACLES = ("v2", "O1", "O2", "O3")
KEYS = ["company_id", "as_of"]


def fact_regular(ops: pd.DataFrame, companies: pd.DataFrame, workers: int) -> pd.DataFrame:
    """Фактическая регулярная обязательная часть по дням: company_id, target_date, reg_in, reg_out."""
    lab = labels_at(ops, ops["operation_date"].max(), workers)
    mask = lab["is_regular"].fillna(False).astype(bool) & lab["category"].isin(reg.MANDATORY_CATEGORIES)
    p = build_panel(ops, companies, regular=mask)
    log.info("оракул регулярности: операций %d из %d", int(mask.sum()), len(ops))
    return p[["company_id", "date", "reg_in", "reg_out"]].rename(columns={"date": "target_date"})


def oracle_variants(bt: pd.DataFrame, events: pd.DataFrame, freg: pd.DataFrame) -> dict[str, pd.DataFrame]:
    bt = bt.drop(columns=["bal_hat", "bal_flow_true", "bal_valid"]).merge(freg, on=["company_id", "target_date"],
                                                                         how="left")
    zero = np.zeros(len(bt))
    ev_in, ev_out = add_events(bt, zero, zero, events, VARIANTS["mandatory"])
    irr_in, irr_out = bt["in_hat"] - ev_in, bt["out_hat"] - ev_out
    reg_in, reg_out = bt["reg_in"].fillna(0.0), bt["reg_out"].fillna(0.0)
    fact_irr_in, fact_irr_out = bt["y_in"] - reg_in, bt["y_out"] - reg_out

    # O3: сумма нерегулярных поступлений модели за горизонт, разложенная по фактическим дням поступлений
    g = bt[KEYS]
    pos_fact = fact_irr_in.clip(lower=0).fillna(0.0)
    tot_fact = pos_fact.groupby([g["company_id"], g["as_of"]]).transform("sum")
    tot_hat = irr_in.groupby([g["company_id"], g["as_of"]]).transform("sum")
    o3_in = np.where(tot_fact > 0, tot_hat * pos_fact / tot_fact.where(tot_fact > 0, 1.0), irr_in)

    out = {
        "v2": (bt["in_hat"], bt["out_hat"]),
        "O1": (fact_irr_in.fillna(irr_in) + ev_in, fact_irr_out.fillna(irr_out) + ev_out),
        "O2": (irr_in + reg_in, irr_out + reg_out),
        "O3": (o3_in + ev_in, bt["out_hat"]),
    }
    base = bt.drop(columns=["reg_in", "reg_out"])
    return {k: add_balance_paths(base.assign(in_hat=np.asarray(i, float), out_hat=np.asarray(o, float), model=k))
            for k, (i, o) in out.items()}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="cashflow_data/cashflow_dataset_participants")
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--run", default="exp_base")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("categorizer").setLevel(logging.WARNING)
    rep = Path(args.reports)
    t0 = time.perf_counter()

    ops, companies = load_dataset(args.data)
    ops = clean_operations(ops)
    freg = fact_regular(ops, companies, default_workers())
    bt = pd.read_parquet(rep / args.run / "backtest_predictions.parquet")
    events = RegularCache.load(rep / "regular_cache_exp").events
    rows = []
    for name, v in oracle_variants(bt, events, freg).items():
        res, _ = calibrate(evaluate_origins(v, name))
        m = pd.concat([metrics_row(v, name, p, res) for p in ("tune", "report")], ignore_index=True)
        d = rep / f"exp_oracle_{name}"
        d.mkdir(exist_ok=True)
        m.to_csv(d / "metrics.csv", index=False)
        rows.append(m)
        log.info("оракул %s готов, %.0f с", name, time.perf_counter() - t0)
    table = pd.concat(rows, ignore_index=True)
    table.to_csv(rep / "oracle.csv", index=False)
    cols = ["row", "period", "company_set", "nmae_bal_d7", "nmae_bal_d30", "strict_precision", "strict_recall",
            "counterfactual_precision", "counterfactual_recall", "coverage_p10_p90"]
    log.info("оракулы:\n%s", table[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
