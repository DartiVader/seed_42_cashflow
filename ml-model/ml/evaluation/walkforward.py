"""Прогон одной компании по всему датасету: каждую неделю прогноз на N рабочих дней вперёд и сравнение с фактом.

    python -m ml.evaluation.walkforward --company C140 [--wd 10] [--run exp_base --model base]

Прогнозы — из backtest (модель фолда обучена только на данных ≤ cutoff < даты прогноза, то есть факт она не
видела), коридор P10–P90 — как в gap_metrics: траектории ошибок, известные к cutoff. Выход:
reports/walkforward_<компания>.csv и reports/figures/walkforward_<компания>.png.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.evaluation.gap_metrics import GapEvalConfig, _pools
from ml.forecast.montecarlo import ALL, McConfig, pick_pool

log = logging.getLogger(__name__)


def walkforward(bt: pd.DataFrame, company_id: str, wd: int, cfg: GapEvalConfig = GapEvalConfig(),
                mc: McConfig = McConfig()) -> pd.DataFrame:
    m = bt[bt["h"] <= cfg.horizon].copy()
    m["industry"] = m["industry"].astype(str)
    m["err_cum_norm"] = ((m["bal_flow_true"] - m["bal_hat"]) / m["scale"]).where(m["bal_valid"])
    c = m[m["company_id"] == company_id]
    rng = np.random.default_rng(cfg.seed)
    pools, rows = {}, []
    for a, g in c.groupby("as_of", sort=True):
        g = g.sort_values("h")
        if len(g) < cfg.horizon:
            continue
        cutoff = g["cutoff"].iloc[0]
        if cutoff not in pools:
            pools[cutoff] = _pools(m, cutoff, cfg.horizon)
        fact = g["bal_true"].to_numpy()[:wd]
        if len(pools[cutoff][ALL]) < mc.min_pool:
            # первые фолды: ошибок прошлых прогнозов ещё нет — только точечный прогноз, без коридора
            paths = g["bal_hat"].to_numpy()[None, :wd]
            p10 = p90 = np.nan
            p50 = float(paths[0, -1])
        else:
            pool = pick_pool(pools[cutoff], g["industry"].iloc[0], mc)
            paths = (g["bal_hat"].to_numpy()[None, :]
                     + pool[rng.integers(len(pool), size=cfg.n_paths)] * g["scale"].iloc[0])[:, :wd]
            p10, p50, p90 = np.percentile(paths[:, -1], [10, 50, 90])
        below = paths < cfg.threshold
        has_band = not np.isnan(p10)
        rows.append({
            "as_of": a, "target_date": g["target_date"].iloc[wd - 1], "period": g["period"].iloc[0],
            "balance_as_of": g["bal_asof"].iloc[0],
            "p10": p10, "p50": p50, "p90": p90, "fact": fact[-1],
            "error": p50 - fact[-1], "error_turnovers": (p50 - fact[-1]) / g["scale"].iloc[0],
            "in_corridor": bool(p10 <= fact[-1] <= p90) if has_band else None,
            "gap_predicted": bool((below.mean(axis=0) >= cfg.p_day_min).any()),
            "gap_probability": float(below.any(axis=1).mean()) if has_band else np.nan,
            "gap_fact": bool((fact < cfg.threshold).any()),
            "min_fact": fact.min(), "valid": bool(g["bal_valid"].iloc[:wd].all()),
        })
    return pd.DataFrame(rows)


def summary(w: pd.DataFrame) -> dict:
    v = w[w["valid"]]
    tp = (v["gap_predicted"] & v["gap_fact"]).sum()
    return {
        "точек": len(v),
        "MAE остатка, ₽": float(v["error"].abs().mean()),
        "MAE в дневных оборотах": float(v["error_turnovers"].abs().mean()),
        "медиана |ошибки|, ₽": float(v["error"].abs().median()),
        "из них с коридором": int(v["in_corridor"].notna().sum()),
        "факт в коридоре P10–P90": float(v["in_corridor"].dropna().astype(bool).mean()),
        "разрывов по факту": int(v["gap_fact"].sum()),
        "предсказано разрывов": int(v["gap_predicted"].sum()),
        "пойманы": int(tp),
    }


def plot(w: pd.DataFrame, daily: pd.DataFrame, company_id: str, wd: int, out: Path) -> None:
    from ml.evaluation import figures as f
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    f._style()
    v = w[w["valid"]]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(daily["date"], daily["balance_eod"], color=f.INK, linewidth=1.5, label="Факт: остаток на конец дня")
    band = v[v["in_corridor"].notna()]
    ax.errorbar(band["target_date"], band["p50"], yerr=[band["p50"] - band["p10"], band["p90"] - band["p50"]], fmt="o",
                color=f.SERIES["lgbm_net"], ecolor=f.BAND, elinewidth=4, markersize=4,
                label=f"Прогноз на {wd} р.д. вперёд: P50 и коридор P10–P90")
    band = v[v["in_corridor"].notna()]
    point = v[v["in_corridor"].isna()]
    ax.scatter(point["target_date"], point["p50"], s=16, color=f.SERIES["lgbm_net"], alpha=0.5, zorder=3,
               label="Прогноз P50 (первые фолды, без коридора)")
    miss = band[~band["in_corridor"].astype(bool)]
    ax.scatter(miss["target_date"], miss["fact"], s=36, facecolors="none", edgecolors=f.SERIES["lgbm"],
               linewidths=1.5, zorder=4, label="Факт вне коридора")
    ax.axhline(0, color=f.MUTED, linewidth=1)
    ax.yaxis.set_major_formatter(f._ruble)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%Y"))
    ax.set_ylabel("Остаток, ₽")
    s = summary(w)
    ax.set_title(f"{company_id}: прогноз каждую неделю на {wd} рабочих дней вперёд против факта\n"
                 f"факт в коридоре P10–P90 в {s['факт в коридоре P10–P90']:.0%} точек, "
                 f"средняя ошибка P50 — {s['MAE в дневных оборотах']:.1f} дневного оборота", fontsize=11)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", default="C140")
    ap.add_argument("--wd", type=int, default=10, help="рабочих дней вперёд (10 ≈ 2 недели)")
    ap.add_argument("--run", default="exp_base", help="каталог backtest в reports/")
    ap.add_argument("--model", default="base")
    ap.add_argument("--reports", default="reports")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rep = Path(args.reports)
    bt = pd.read_parquet(rep / args.run / "backtest_predictions.parquet", filters=[("model", "==", args.model)])
    w = walkforward(bt, args.company, args.wd)
    w.to_csv(rep / f"walkforward_{args.company}.csv", index=False)
    from ml.data.loaders import load_dataset
    from ml.forecast.panel import build_panel
    from ml.pipeline.clean import clean_operations
    ops, companies = load_dataset("cashflow_data/cashflow_dataset_participants")
    ops = clean_operations(ops[ops["company_id"] == args.company])
    daily = build_panel(ops, companies)
    daily = daily[daily["date"] >= w["as_of"].min()]
    (rep / "figures").mkdir(exist_ok=True)
    plot(w, daily, args.company, args.wd, rep / "figures" / f"walkforward_{args.company}.png")
    log.info("итог: %s", summary(w))


if __name__ == "__main__":
    main()
