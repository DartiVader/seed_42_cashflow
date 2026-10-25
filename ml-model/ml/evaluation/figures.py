"""Графики для презентации из готовых отчётов → reports/figures/*.png.

    python -m ml.evaluation.figures [--reports reports] [--company C140] [--as-of 2026-08-28]

1. horizon.png      — ошибка остатка по горизонту: zero / lgbm / lgbm_net, new_dates и new_companies;
2. company.png      — компания: коридор P10–P90, P50 и факт (точка backtest, модель её не видела);
3. reliability.png  — диаграмма надёжности вероятности разрыва до и после калибровки;
4. gaps_pr.png      — precision / recall разрывов: модели против нуля, две метки;
5. ablation.png     — абляция регулярных событий (если есть reports/ablation.csv).
Все данные — period=report (фолды, не участвовавшие в подборе).
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.evaluation.gap_metrics import GapEvalConfig, _pools  # noqa: E402
from ml.forecast.montecarlo import McConfig, pick_pool  # noqa: E402

log = logging.getLogger(__name__)

# эталонная палитра (dataviz, references/palette.md), светлая тема; первые три слота различимы попарно
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
SERIES = {"lgbm_net": "#2a78d6", "lgbm": "#eb6834", "zero": "#1baf7a"}
LABELS = {"lgbm_net": "lgbm_net (основная)", "lgbm": "lgbm", "zero": "ноль (остаток не меняется)"}
BAND = "#cde2fb"
SETS = {"new_dates": "Новые даты", "new_companies": "Новые компании (холдаут)"}


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "text.color": INK, "xtick.color": INK_2,
        "ytick.color": INK_2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "font.size": 10, "legend.frameon": False, "lines.linewidth": 2,
        "figure.dpi": 150,
    })


def _ruble(v: float, _=None) -> str:
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f} млн".replace(".", ",")
    return f"{v / 1e3:.0f} тыс." if abs(v) >= 1e3 else f"{v:.0f}"


def horizon(bt: pd.DataFrame, out: Path) -> None:
    rep = bt[(bt["period"] == "report") & bt["bal_valid"] & bt["model"].isin(SERIES)]
    rep = rep.assign(err=(rep["bal_hat"] - rep["bal_flow_true"]).abs() / rep["scale"])
    t = rep.groupby(["company_set", "model", "h"])["err"].mean()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, (cs, title) in zip(axes, SETS.items()):
        ends = {}
        for m in SERIES:
            s = t.loc[(cs, m)]
            ax.plot(s.index, s.to_numpy(), color=SERIES[m], label=LABELS[m])
            ends[m] = (s.index[-1], s.iloc[-1])
        _end_labels(ax, ends)
        ax.set_title(title)
        ax.set_xlabel("Горизонт, рабочих дней")
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel("Ошибка остатка, дневных оборотов")
    axes[0].legend(loc="upper left")
    fig.suptitle("Ошибка остатка по горизонту: на новых датах модели точнее нуля, на новых компаниях — вровень",
                 x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "horizon.png")
    plt.close(fig)


def _end_labels(ax, ends: dict, min_gap: float = 0.2) -> None:
    """Значения на концах линий, раздвинутые по вертикали, чтобы не наезжали."""
    items = sorted(ends.items(), key=lambda kv: kv[1][1])
    y_prev = -np.inf
    for m, (x, y) in items:
        y_txt = max(y, y_prev + min_gap)
        ax.annotate(f"{y:.2f}", (x, y), xytext=(x + 0.4, y_txt), textcoords="data", va="center",
                    color=INK_2, fontsize=9, annotation_clip=False)
        y_prev = y_txt


def company(bt: pd.DataFrame, out: Path, company_id: str, as_of: str | None, model: str = "lgbm_net") -> None:
    """Коридор как в gap_metrics: прогноз остатка + траектории ошибок, известные к cutoff фолда."""
    cfg, mc = GapEvalConfig(), McConfig()
    m = bt[(bt["model"] == model) & (bt["h"] <= cfg.horizon)].copy()
    m["industry"] = m["industry"].astype(str)
    m["err_cum_norm"] = ((m["bal_flow_true"] - m["bal_hat"]) / m["scale"]).where(m["bal_valid"])
    c = m[(m["company_id"] == company_id) & (m["period"] == "report")]
    full = c.groupby("as_of").filter(lambda g: len(g) == cfg.horizon and g["bal_valid"].all())
    if full.empty:
        log.warning("%s: нет точки report с полным горизонтом — график компании пропущен", company_id)
        return
    a = pd.Timestamp(as_of) if as_of else full["as_of"].max()   # по умолчанию — последняя, без выбора по факту
    g = full[full["as_of"] == a].sort_values("h")
    pool = pick_pool(_pools(m, g["cutoff"].iloc[0], cfg.horizon), g["industry"].iloc[0], mc)
    rng = np.random.default_rng(cfg.seed)
    paths = g["bal_hat"].to_numpy()[None, :] + pool[rng.integers(len(pool), size=cfg.n_paths)] * g["scale"].iloc[0]
    p10, p50, p90 = np.percentile(paths, [10, 50, 90], axis=0)
    d = g["target_date"]
    b0 = g["bal_asof"].iloc[0]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.fill_between(d, p10, p90, color=BAND, linewidth=0, label="Коридор P10–P90")
    ax.plot(d, p50, color=SERIES[model], label="Прогноз P50")
    ax.plot(d, g["bal_true"], color=INK, label="Факт", marker="o", markersize=3.5)
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.scatter([a], [b0], color=INK, s=30, zorder=3)
    ax.annotate(f"остаток на {a:%d.%m}:\n{_ruble(b0)} ₽", (a, b0), xytext=(-4, -10), textcoords="offset points",
                color=INK_2, fontsize=9, ha="right", va="top")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.set_xlim(a - pd.Timedelta(days=4), d.iloc[-1] + pd.Timedelta(days=1))
    ax.yaxis.set_major_formatter(_ruble)
    ax.set_ylabel("Остаток, ₽")
    inside = float(((g["bal_true"] >= p10) & (g["bal_true"] <= p90)).mean())
    ax.set_title(f"{company_id}: прогноз от {a:%d.%m.%Y} на {cfg.horizon} рабочих дней и факт "
                 f"(в коридоре {inside:.0%} дней)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "company.png")
    plt.close(fig)


def reliability(rel: pd.DataFrame, out: Path, model: str = "lgbm_net") -> None:
    r = rel[rel["model"] == model]
    fig, ax = plt.subplots(figsize=(5.2, 5))
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle="--", label="Идеальная калибровка")
    for col, color, label in (("probability", SERIES["lgbm"], "До калибровки"),
                              ("probability_cal", SERIES["lgbm_net"], "После (isotonic на tune)")):
        s = r[r["prob"] == col].sort_values("prob_mean")
        ax.plot(s["prob_mean"], s["fact_rate"], color=color, marker="o", markersize=6, label=label)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Прогнозная вероятность разрыва")
    ax.set_ylabel("Доля точек, где разрыв случился")
    ax.set_title(f"Надёжность вероятности, {model}\n(метка counterfactual, period=report)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "reliability.png")
    plt.close(fig)


def gaps_pr(gm: pd.DataFrame, out: Path, company_set: str = "new_dates") -> None:
    g = gm[(gm["period"] == "report") & (gm["start"] == "positive") & (gm["company_set"] == company_set)
           & gm["model"].isin(SERIES) & gm["label"].isin(["strict", "counterfactual"])]
    titles = {"strict": "Фактический минус (strict)", "counterfactual": "Минус без денег владельца (counterfactual)"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    width = 0.26
    for ax, (label, title) in zip(axes, titles.items()):
        s = g[g["label"] == label].set_index("model")
        n_true = int(s["true_gaps"].iloc[0])
        for i, m in enumerate(SERIES):
            vals = [s.at[m, "precision"], s.at[m, "recall"]]
            x = np.arange(2) + (i - 1) * (width + 0.02)
            ax.bar(x, vals, width=width, color=SERIES[m], label=LABELS[m])
            for xi, v in zip(x, vals):
                ax.annotate(f"{v:.2f}", (xi, v), xytext=(0, 3), textcoords="offset points", ha="center",
                            color=INK_2, fontsize=8)
        ax.set_xticks(range(2), ["precision", "recall"])
        ax.set_ylim(0, 1)
        ax.grid(axis="x", visible=False)
        ax.set_title(f"{title}\nфактических разрывов: {n_true}", fontsize=11)
    axes[0].set_ylabel("Доля")
    axes[0].legend(loc="upper left")
    fig.suptitle(f"Кассовые разрывы: модели против нуля ({SETS[company_set].lower()}, period=report)",
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "gaps_pr.png")
    plt.close(fig)


ABLATION_NAMES = {
    "1_no_events": "Без событий", "2_tax": "+ налоги", "3_tax_salary": "+ зарплата",
    "4_mandatory": "+ аренда, кредит, лизинг,\nкоммунальные, связь", "5_mandatory_revenue": "+ регулярные поступления",
    "zero_all_events": "Ноль + все события",
}


def ablation(abl: pd.DataFrame, out: Path, metric: str = "nmae_bal_d30") -> None:
    rows = [r for r in ABLATION_NAMES if r in set(abl["row"])]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, (cs, title) in zip(axes, SETS.items()):
        s = abl[abl["company_set"] == cs].set_index("row").reindex(rows)[metric]
        y = np.arange(len(rows))[::-1]
        colors = [SERIES["zero"] if r.startswith("zero") else SERIES["lgbm_net"] for r in rows]
        ax.barh(y, s.to_numpy(), color=colors, height=0.6)
        for yi, v in zip(y, s.to_numpy()):
            ax.annotate(f"{v:.2f}", (v, yi), xytext=(4, 0), textcoords="offset points", va="center",
                        color=INK_2, fontsize=9)
        ax.set_yticks(y, [ABLATION_NAMES[r] for r in rows])
        ax.grid(axis="y", visible=False)
        ax.set_title(title)
        ax.set_xlabel("Ошибка остатка на 30 днях, дневных оборотов")
    fig.suptitle("Вклад регулярных событий (lgbm_net, переобучение на каждой строке)", x=0.01, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "ablation.png")
    plt.close(fig)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--company", default="C140")
    ap.add_argument("--as-of", default=None, help="точка backtest; по умолчанию последняя с полным горизонтом")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _style()
    rep = Path(args.reports)
    out = rep / "figures"
    out.mkdir(parents=True, exist_ok=True)
    bt = pd.read_parquet(rep / "backtest_predictions.parquet", filters=[("model", "in", list(SERIES))])
    horizon(bt, out)
    company(bt, out, args.company, args.as_of)
    reliability(pd.read_csv(rep / "gap_reliability.csv"), out)
    gaps_pr(pd.read_csv(rep / "gap_metrics.csv"), out)
    if (rep / "ablation.csv").exists():
        ablation(pd.read_csv(rep / "ablation.csv"), out)
    else:
        log.info("reports/ablation.csv ещё нет — график абляции пропущен")
    log.info("графики: %s", sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main()
