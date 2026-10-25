"""Эксперимент 8.6: вероятность разрыва моделью выживаемости с дискретным временем вместо Монте-Карло.

    python -m ml.evaluation.hazard [--run exp_base]

LightGBM-классификатор hazard_h = P(разрыв в день as_of+h | до него разрыва не было), h = 1…21 р.д.
P(разрыв за 30 дней) = 1 − ∏(1 − hazard_h). Разрыв — CF-метка, как у CF-метрики: остаток без спасающих
поступлений ниже нуля (gap_metrics). Точки с остатком уже ниже нуля на as_of не участвуют.

Признаки — v2 (feature_columns("base"), в них уже есть h) плюс то, без чего вероятность разрыва не
выучить: остаток на as_of в оборотах (bal_scale) и прогнозная траектория v2 — P50 остатка на день h и её
минимум до h (bal_hat из backtest, out-of-time). Всё известно на as_of.

Обучение — как backtest: на каждом месячном cutoff учимся на днях с целевой датой ≤ cutoff (незакончившиеся
горизонты — цензурированные строки, это нормально для дискретной выживаемости), без холдаута,
прогнозируем точки фолда. Фолд без хотя бы MIN_EVENTS разрывов в обучении пропускается, и точка
сравнивается с МК только там, где есть обе вероятности.
Выход: reports/hazard.csv (Brier и калибровка), reports/hazard_reliability.csv, reports/figures/hazard_reliability.png.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.evaluation.calibration import reliability
from ml.evaluation.gap_metrics import CALIBRATION_LABEL, GapEvalConfig, calibrate, evaluate_origins
from ml.forecast.features import CAT_FEATURES, feature_columns

log = logging.getLogger("ml.hazard")

HORIZON = GapEvalConfig().horizon
PATH_FEATURES = ["bal_scale", "path_scale", "path_min_scale"]
FEATURES = feature_columns("base") + PATH_FEATURES
KEYS = ["company_id", "as_of"]
MIN_EVENTS = 30
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=100,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
              deterministic=True, force_row_wise=True, num_threads=4, verbose=-1)
NUM_ROUNDS = 300


def survival_table(bt: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """Строки (точка, h ≤ HORIZON) с признаками и меткой: event — первый день CF-разрыва, at_risk — до него
    разрыва не было (включая сам день разрыва). Дни после пропуска в данных не участвуют."""
    t = bt[bt["h"] <= HORIZON].sort_values(KEYS + ["h"]).reset_index(drop=True)
    t = t[t["bal_asof"] >= 0]
    cols = [c for c in feature_columns("base") + ["bal_scale"] if c not in t.columns]
    t = t.merge(feats[KEYS + ["h"] + cols], on=KEYS + ["h"], how="left", validate="one_to_one")
    t["path_scale"] = t["bal_hat"] / t["scale"]
    t["path_min_scale"] = t["path_scale"].groupby([t["company_id"], t["as_of"]]).cummin()
    gap = (t["bal_true"] - t["rescue_true"]) < 0
    t["valid"] = t["bal_valid"].astype(bool).groupby([t["company_id"], t["as_of"]]).cummin()
    before = gap.astype(int).groupby([t["company_id"], t["as_of"]]).cumsum() - gap.astype(int)
    t["event"] = gap & (before == 0)
    t["at_risk"] = before == 0
    return t


def _matrix(t: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    X = t[FEATURES].copy()
    for c in CAT_FEATURES:
        X[c] = pd.Categorical(X[c].astype(str), categories=categories[c])
    return X


def fit_predict(t: pd.DataFrame, holdout: set[str], seed: int = 42) -> pd.DataFrame:
    """По точке на (компания, as_of) прогнозного фолда: probability_hazard."""
    categories = {c: sorted(t[c].astype(str).unique()) for c in CAT_FEATURES}
    out = []
    for cutoff in sorted(t["cutoff"].unique()):
        train = t[(t["target_date"] <= cutoff) & t["valid"] & t["at_risk"] & ~t["company_id"].isin(holdout)]
        n_ev = int(train["event"].sum())
        if n_ev < MIN_EVENTS:
            log.info("cutoff %s: в обучении %d разрывов — фолд пропущен", pd.Timestamp(cutoff).date(), n_ev)
            continue
        assert train["target_date"].max() <= cutoff
        ds = lgb.Dataset(_matrix(train, categories), train["event"].astype(int), categorical_feature=CAT_FEATURES)
        booster = lgb.train({**PARAMS, "seed": seed}, ds, num_boost_round=NUM_ROUNDS)
        fold = t[t["cutoff"] == cutoff]
        hz = booster.predict(_matrix(fold, categories))
        surv = pd.Series(np.log1p(-np.clip(hz, 0, 1 - 1e-9)), index=fold.index).groupby(
            [fold["company_id"], fold["as_of"]]).sum()
        out.append((1 - np.exp(surv)).rename("probability_hazard").reset_index())
        log.info("cutoff %s: строк %d, разрывов %d, точек фолда %d", pd.Timestamp(cutoff).date(), len(train), n_ev,
                 len(surv))
    return pd.concat(out, ignore_index=True)


def compare(res: pd.DataFrame) -> pd.DataFrame:
    """Brier и калибровка-в-целом трёх вероятностей на общих точках."""
    truth = f"true_gap_{CALIBRATION_LABEL}"
    probs = {"mc_raw": "probability", "mc_cal": "probability_cal", "hazard": "probability_hazard"}
    rows = []
    for (period, cs), g in res.groupby(["period", "company_set"]):
        y = g[truth].astype(float)
        base = {"period": period, "company_set": cs, "n_origins": len(g), "gap_rate": y.mean(),
                "brier_climatology": ((y.mean() - y) ** 2).mean()}
        for name, col in probs.items():
            p = g[col].clip(1e-6, 1 - 1e-6)
            rows.append({**base, "prob": name, "brier": ((p - y) ** 2).mean(), "prob_mean": p.mean(),
                         "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
                         "ece": _ece(p.to_numpy(), y.to_numpy()), "auc": _auc(p.to_numpy(), y.to_numpy())})
    return pd.DataFrame(rows)


def _auc(p: np.ndarray, y: np.ndarray) -> float:
    """ROC AUC через ранги (Манн — Уитни): различает ли вероятность точки с разрывом и без."""
    pos, n = int(y.sum()), len(y)
    if pos in (0, n):
        return np.nan
    r = pd.Series(p).rank().to_numpy()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (n - pos)))


def _ece(p: np.ndarray, y: np.ndarray, bins=(0, .05, .1, .2, .4, .6, .8, 1.0)) -> float:
    r = reliability(p, y, bins)
    return float((r["n"] * (r["prob_mean"] - r["fact_rate"]).abs()).sum() / r["n"].sum())


def reliability_figure(rel: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from ml.evaluation.figures import GRID, INK_2, MUTED, SURFACE, _style
    _style()
    colors = {"mc_cal": "#2a78d6", "hazard": "#eb6834", "mc_raw": MUTED}
    names = {"mc_cal": "Монте-Карло, калибровка", "hazard": "Выживаемость (hazard)", "mc_raw": "Монте-Карло, сырая"}
    sets = [s for s in ("new_dates", "new_companies") if s in set(rel["company_set"])]
    fig, axes = plt.subplots(1, len(sets), figsize=(5.2 * len(sets), 4.6), facecolor=SURFACE, squeeze=False)
    for ax, cs in zip(axes[0], sets):
        ax.plot([0, 1], [0, 1], color=GRID, lw=1.5, zorder=1)
        for name in ("mc_raw", "mc_cal", "hazard"):
            r = rel[(rel["company_set"] == cs) & (rel["prob"] == name)]
            ax.plot(r["prob_mean"], r["fact_rate"], color=colors[name], lw=2, zorder=3,
                    ls="--" if name == "mc_raw" else "-", label=names[name])
            ax.scatter(r["prob_mean"], r["fact_rate"], s=np.clip(r["n"], 12, 160), color=colors[name],
                       edgecolor=SURFACE, linewidth=2, zorder=4)
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Предсказанная вероятность разрыва за 30 дней",
               ylabel="Доля точек с разрывом (CF)")
        ax.set_title({"new_dates": "Новые даты", "new_companies": "Новые компании (холдаут)"}[cs],
                     color=INK_2, loc="left")
    axes[0][0].legend(frameon=False, loc="upper left")
    fig.suptitle("Надёжность вероятности разрыва, period=report (размер точки — число точек в корзине)",
                 color=INK_2, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--run", default="exp_base")
    ap.add_argument("--rows", default="regular_cache_exp/rows_mandatory.parquet")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rep = Path(args.reports)
    t0 = time.perf_counter()

    bt = pd.read_parquet(rep / args.run / "backtest_predictions.parquet")
    feats = pd.read_parquet(rep / args.rows)
    holdout = set(bt.loc[bt["company_set"] == "new_companies", "company_id"])
    t = survival_table(bt, feats)
    hz = fit_predict(t, holdout, args.seed)

    name = args.run.removeprefix("exp_")
    res, _ = calibrate(evaluate_origins(bt.assign(model=name), name))
    res = res[res["start"] == "positive"].merge(hz, on=KEYS, how="inner")
    res.to_parquet(rep / "hazard_origins.parquet", index=False)
    table = compare(res)
    table.to_csv(rep / "hazard.csv", index=False)
    rel = []
    for cs, g in res[res["period"] == "report"].groupby("company_set"):
        for pname, col in (("mc_raw", "probability"), ("mc_cal", "probability_cal"), ("hazard", "probability_hazard")):
            rel.append(reliability(g[col].to_numpy(), g[f"true_gap_{CALIBRATION_LABEL}"].to_numpy())
                       .assign(company_set=cs, prob=pname))
    rel = pd.concat(rel, ignore_index=True)
    rel.assign(bin=rel["bin"].astype(str)).to_csv(rep / "hazard_reliability.csv", index=False)
    (rep / "figures").mkdir(exist_ok=True)
    reliability_figure(rel, rep / "figures" / "hazard_reliability.png")
    log.info("hazard против МК (%.0f с):\n%s", time.perf_counter() - t0,
             table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
