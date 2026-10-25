"""8.5: насколько v2_cf пессимистичнее v2 перед реальными разрывами.

    python -m ml.evaluation.pre_gap_shift [--base exp_base] [--cf exp_v2_cf]

Точки — (компания, as_of) с положительным остатком на as_of, у которых CF-разрыв наступает в ближайшие
WINDOW_WD рабочих дней (h* = true_h_counterfactual ≤ 5). Для каждой:
  shift_gap_scale — (P50 v2 − P50 v2_cf) в день провала h*, в дневных оборотах: > 0 — v2_cf пессимистичнее;
  shift_min_scale — то же для минимума P50 на 1…h*;
  dprob_cal       — калиброванная вероятность разрыва v2_cf минус v2.
Для сравнения — тот же сдвиг P50 на h = 5 у точек без разрыва за горизонт (не пессимистичнее ли
v2_cf вообще всегда). Выход: reports/v2_cf_pre_gap_shift.csv; в лог — только доли и обороты, без рублей.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.evaluation.gap_metrics import CALIBRATION_LABEL, calibrate, evaluate_origins

log = logging.getLogger("ml.pre_gap_shift")

WINDOW_WD = 5
KEYS = ["company_id", "as_of"]


def _paths(bt: pd.DataFrame) -> pd.DataFrame:
    return bt.pivot_table(index=KEYS, columns="h", values="bal_hat")


def shift_table(bt_v2: pd.DataFrame, bt_cf: pd.DataFrame, res_v2: pd.DataFrame, res_cf: pd.DataFrame,
                window_wd: int = WINDOW_WD) -> pd.DataFrame:
    """По строке на точку перед разрывом (kind=pre_gap) и на точку без разрыва (kind=no_gap)."""
    lab = CALIBRATION_LABEL
    cols = KEYS + ["company_set", "period", "scale", "start", f"true_gap_{lab}", f"true_h_{lab}",
                   "pred_gap", "probability_cal"]
    r = res_v2[cols].merge(res_cf[KEYS + ["pred_gap", "probability_cal"]], on=KEYS, suffixes=("_v2", "_cf"))
    r = r[r["start"] == "positive"]
    pv2, pcf = _paths(bt_v2), _paths(bt_cf)
    idx = pd.MultiIndex.from_frame(r[KEYS])
    a, b = pv2.reindex(idx).to_numpy(), pcf.reindex(idx).to_numpy()
    gap = r[f"true_gap_{lab}"].astype(bool).to_numpy()
    h = np.where(gap, r[f"true_h_{lab}"].fillna(0).to_numpy(), WINDOW_WD).astype(int)
    rows = np.arange(len(r))
    hs = h.clip(1) - 1
    cummin = lambda p: np.minimum.accumulate(p, axis=1)
    scale = r["scale"].to_numpy()
    r = r.assign(
        kind=np.where(gap & (h <= window_wd), "pre_gap", np.where(~gap, "no_gap", "later_gap")),
        shift_gap_scale=(a[rows, hs] - b[rows, hs]) / scale,
        shift_min_scale=(cummin(a)[rows, hs] - cummin(b)[rows, hs]) / scale,
        shift_gap_rub=a[rows, hs] - b[rows, hs],
        dprob_cal=r["probability_cal_cf"] - r["probability_cal_v2"],
    )
    return r[r["kind"] != "later_gap"]


def summarize_shift(t: pd.DataFrame) -> pd.DataFrame:
    def one(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "n_origins": len(g),
            "shift_gap_scale_mean": g["shift_gap_scale"].mean(),
            "shift_gap_scale_median": g["shift_gap_scale"].median(),
            "shift_min_scale_mean": g["shift_min_scale"].mean(),
            "share_cf_more_pessimistic": (g["shift_gap_scale"] > 0).mean(),
            "share_cf_less_pessimistic": (g["shift_gap_scale"] < 0).mean(),
            "shift_gap_rub_median": g["shift_gap_rub"].median(),
            "dprob_cal_mean": g["dprob_cal"].mean(),
            "caught_v2": g["pred_gap_v2"].mean(),
            "caught_cf": g["pred_gap_cf"].mean(),
        })
    return t.groupby(["kind", "period", "company_set"]).apply(one, include_groups=False).reset_index()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--base", default="exp_base")
    ap.add_argument("--cf", default="exp_v2_cf")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rep = Path(args.reports)
    bts, ress = [], []
    for run in (args.base, args.cf):
        bt = pd.read_parquet(rep / run / "backtest_predictions.parquet")
        res, _ = calibrate(evaluate_origins(bt.assign(model=run), run))
        bts.append(bt)
        ress.append(res)
    s = summarize_shift(shift_table(*bts, *ress))
    s.to_csv(rep / "v2_cf_pre_gap_shift.csv", index=False)
    log.info("сдвиг v2_cf относительно v2 (> 0 — пессимистичнее, в дневных оборотах):\n%s",
             s.drop(columns=["shift_gap_rub_median"]).to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
