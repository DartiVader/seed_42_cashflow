"""9.3: порог тревоги GapConfig.p_day_min — подбор по F1 (CF) строго на tune-фолдах backtest.

    python -m ml.evaluation.threshold [--run exp_base]

Разрыв в прогнозе = первый день, где доля траекторий МК ниже порога ≥ p_day_min, поэтому статус
gap_expected при пороге t — это max_p_day ≥ t (gap_metrics.evaluate_origins). Порог выбирается по F1 CF-метки
на period=tune, company_set=new_dates, остаток на as_of > 0; при равенстве — ближе к текущему 0,3.
Затем без изменений применяется к report (новые даты) и к холдауту компаний (report и все периоды).
Решение о продукте — по холдауту: если F1 там растёт, порог идёт в GapConfig.
Выход: reports/threshold.csv (сетка), reports/threshold_choice.csv (0,3 против подобранного),
reports/figures/threshold.png.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.evaluation.gap_metrics import CALIBRATION_LABEL, evaluate_origins

log = logging.getLogger("ml.threshold")

GRID = np.round(np.arange(0.05, 0.951, 0.05), 2)
CURRENT = 0.3   # порог до 9.3; в продукте сейчас GapConfig().p_day_min
SETS = {
    "tune: новые даты (подбор)": lambda r: (r["period"] == "tune") & (r["company_set"] == "new_dates"),
    "report: новые даты": lambda r: (r["period"] == "report") & (r["company_set"] == "new_dates"),
    "report: холдаут компаний": lambda r: (r["period"] == "report") & (r["company_set"] == "new_companies"),
    "холдаут, все периоды": lambda r: r["company_set"] == "new_companies",
}


def scores(r: pd.DataFrame, t: float, label: str = CALIBRATION_LABEL) -> dict:
    y = r[f"true_gap_{label}"].astype(bool).to_numpy()
    p = r["max_p_day"].to_numpy() >= t
    tp, fp, fn, tn = int((p & y).sum()), int((p & ~y).sum()), int((~p & y).sum()), int((~p & ~y).sum())
    prec = tp / (tp + fp) if tp + fp else np.nan
    rec = tp / (tp + fn) if tp + fn else np.nan
    f1 = 2 * prec * rec / (prec + rec) if tp else 0.0
    return {"threshold": t, "n": len(y), "accuracy": (tp + tn) / len(y), "precision": prec, "recall": rec, "f1": f1,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def grid_table(res: pd.DataFrame) -> pd.DataFrame:
    res = res[res["start"] == "positive"]
    return pd.DataFrame([{"set": name, **scores(res[f(res)], t)} for name, f in SETS.items() for t in GRID])


def choose(grid: pd.DataFrame) -> float:
    tune = grid[grid["set"] == next(iter(SETS))].copy()
    tune["dist"] = (tune["threshold"] - CURRENT).abs()
    return float(tune.sort_values(["f1", "dist"], ascending=[False, True])["threshold"].iloc[0])


def figure(grid: pd.DataFrame, best: float, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from ml.evaluation.figures import INK_2, MUTED, SURFACE, _style
    _style()
    names = list(SETS)
    colors = {names[0]: "#2a78d6", names[1]: "#1baf7a", names[2]: "#eb6834"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), facecolor=SURFACE)
    t = grid[grid["set"] == names[0]]
    ax = axes[0]
    for col, ls, lab in (("f1", "-", "F1"), ("precision", "--", "Precision"), ("recall", ":", "Recall")):
        ax.plot(t["threshold"], t[col], color="#2a78d6", ls=ls, lw=2, label=lab)
    ax.set_title("Подбор: tune, новые даты (CF)", color=INK_2, loc="left")
    ax = axes[1]
    for name in names[:3]:
        g = grid[grid["set"] == name]
        ax.plot(g["threshold"], g["f1"], color=colors[name], lw=2, label=name)
    ax.set_title("F1 на tune, report и холдауте", color=INK_2, loc="left")
    for ax in axes:
        ax.axvline(CURRENT, color=MUTED, lw=1, ls=":")
        ax.axvline(best, color=MUTED, lw=1.5)
        ax.text(CURRENT, 0.02, f" было {CURRENT:.2f}".replace(".", ","), color=MUTED, fontsize=8)
        ax.text(best, 0.08, f" подобран {best:.2f}".replace(".", ","), color=MUTED, fontsize=8)
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Порог p_day_min (доля траекторий ниже нуля в день)")
        ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--run", default="exp_base")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rep = Path(args.reports)
    bt = pd.read_parquet(rep / args.run / "backtest_predictions.parquet")
    name = args.run.removeprefix("exp_")
    res = evaluate_origins(bt.assign(model=name), name)
    grid = grid_table(res)
    best = choose(grid)
    grid.to_csv(rep / "threshold.csv", index=False)
    choice = grid[grid["threshold"].isin([CURRENT, best])].sort_values(["set", "threshold"])
    choice.to_csv(rep / "threshold_choice.csv", index=False)
    (rep / "figures").mkdir(exist_ok=True)
    figure(grid, best, rep / "figures" / "threshold.png")
    log.info("порог по F1 на tune: %.2f (был %.2f)\n%s", best, CURRENT,
             choice.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
