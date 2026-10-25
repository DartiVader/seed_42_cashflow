"""9.1: отчёт по контрольному датасету — продуктовый forecast() против факта.

    python -m ml.evaluation.control --data <папка датасета> [--out reports/control] [--workers 6]

Датасет — в формате кейса (statements/, all_operations.csv, companies.csv). Модель, калибровка и пул ошибок —
продуктовая версия из models/ (без переобучения). Точки прогноза — последний рабочий день каждого месяца,
для которого в данных есть следующие 30 календарных дней без пропусков. На каждой точке — ровно тот же
forecast(), что отвечает предпринимателю (advice=False: советы на метрики не влияют), данные ≤ as_of.

Метрики:
- разрыв за 30 дней по двум меткам правды (как в backtest, ml.evaluation.gap_metrics): strict — фактический
  остаток < 0; counterfactual (CF) — остаток без спасающих поступлений (свои переводы из другого банка, деньги
  учредителя) < 0. Точки с остатком < 0 уже на as_of — отдельно, в классификацию не входят;
  accuracy, precision, recall, F1 по статусу gap_expected; ROC-AUC, Brier, ECE по вероятности провала
  (сырая доля траекторий МК и калиброванная isotonic — trace, шаг 7); матрицы ошибок CF и strict;
- остаток P50 на 1/7/14/30 календарных дней: MAE, MSE, RMSE в ₽, nMAE в дневных оборотах, покрытие P10–P90;
- бейзлайны: «остаток не меняется», dow_mean (остаток), «тренд 60 рабочих дней» (разрывы), для вероятности — климатология (доля разрывов
  в самом наборе — подсказка из будущего, это нижняя граница Brier, а не честный соперник), для AUC — «низкий
  остаток» (−остаток / оборот).
Выход в --out: summary.md, run.log, metrics_*.csv, origins.parquet, daily.parquet, figures/*.png.
На датасете участников продуктовая модель видела все даты (обучена до 30.09.2026): метрики in-sample, кроме
холдаута компаний — он показан отдельной строкой. Честные out-of-time цифры — backtest (reports/experiments.csv).
"""
from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import shutil
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.calendar import all_working_days
from ml.evaluation.calibration import reliability
from ml.forecast.api import ForecastContext, forecast
from ml.forecast.contracts import CompanyClosedError, ForecastError
from ml.forecast.gaps import GapConfig
from ml.forecast.models import DowMean
from ml.forecast.trace import format_steps

log = logging.getLogger("ml.control")

HORIZON_DAYS = 30
REPORT_DAYS = (1, 7, 14, 30)
TREND_WD = 60
LABELS = ("counterfactual", "strict")
PROBS = {"mc_raw": "prob_raw", "mc_cal": "prob_cal"}
DEFAULT_DATA = "cashflow_data/cashflow_dataset_participants"
ECE_BINS = (0, .05, .1, .2, .4, .6, .8, 1.0)
OLD_THRESHOLD = 0.3                      # порог тревоги до 9.3
THRESHOLD = GapConfig().p_day_min        # в продукте
PRODUCT = f"v2 (продукт: порог {THRESHOLD:.2f}, isotonic)".replace(".", ",")
OLD = f"v2, порог {OLD_THRESHOLD:.2f}".replace(".", ",")

_CTX: ForecastContext | None = None   # контекст процесса-исполнителя


def month_origins(panel: pd.DataFrame, horizon_days: int = HORIZON_DAYS) -> pd.DataFrame:
    """Последний рабочий день месяца с данными компании, если данные покрывают as_of + horizon_days."""
    out = []
    for cid, g in panel.groupby("company_id", sort=True):
        last = g["date"].max()
        ends = g.groupby(g["date"].dt.to_period("M"))["date"].max()
        ends = ends[(ends + pd.Timedelta(days=horizon_days) <= last) & (ends == _last_wd_of_month(ends))]
        out += [(cid, d) for d in ends]
    return pd.DataFrame(out, columns=["company_id", "as_of"])


def _last_wd_of_month(d: pd.Series) -> pd.Series:
    wd = all_working_days()
    m_end = d.dt.to_period("M").dt.end_time.dt.normalize()
    return pd.Series(wd[wd.searchsorted(m_end.to_numpy(), side="right") - 1], index=d.index)


def _run_one(key: tuple[str, pd.Timestamp]) -> dict:
    cid, as_of = key
    t0 = time.perf_counter()
    try:
        r = forecast(cid, as_of.date(), HORIZON_DAYS, seed=42, context=_CTX, advice=False)
    except CompanyClosedError:
        return {"company_id": cid, "as_of": as_of, "error": "closed"}
    except ForecastError:
        return {"company_id": cid, "as_of": as_of, "error": "forecast_error"}
    step7 = r.trace[6]["values"]
    return {"company_id": cid, "as_of": as_of, "error": None, "status": r.status,
            "prob_raw": step7["probability_raw"], "prob_cal": step7["probability"], "max_p_day": step7["max_p_day"],
            "dow": _dow_path(cid, as_of),
            "pred_date": pd.Timestamp(r.gaps[0].date) if r.gaps else pd.NaT,
            "daily": [(d.date, d.p10, d.p50, d.p90) for d in r.daily], "seconds": time.perf_counter() - t0}


def _dow_path(cid: str, as_of: pd.Timestamp) -> list[tuple[pd.Timestamp, float]]:
    """Бейзлайн dow_mean: остаток + среднее по дню недели за 8 недель (поток без своих переводов и разовых)."""
    h = _CTX.panel[(_CTX.panel["company_id"] == cid) & (_CTX.panel["date"] <= as_of)]
    wd = all_working_days()
    anchor = h["date"].iloc[-1]
    n = int(((wd > anchor) & (wd <= as_of + pd.Timedelta(days=HORIZON_DAYS))).sum())
    pred = DowMean().predict(h, anchor, n)
    bal = float(h["balance_eod"].iloc[-1]) + np.cumsum(pred["in_hat"].to_numpy() - pred["out_hat"].to_numpy())
    return list(zip(pred["target_date"], bal))


def _init_worker(data: str, models: str) -> None:
    global _CTX
    logging.getLogger("categorizer").setLevel(logging.WARNING)
    _CTX = ForecastContext.load(data, models, "reports/backtest_residuals.parquet")


def run_forecasts(ctx: ForecastContext, origins: pd.DataFrame, workers: int, data: str, models: str) -> list[dict]:
    """spawn, а не fork: LightGBM (OpenMP) в дочернем процессе после fork зависает. Каждый процесс сам
    загружает контекст (~7 с, параллельно)."""
    global _CTX
    _CTX = ctx
    keys = list(origins.itertuples(index=False, name=None))
    if workers <= 1:
        return [_run_one(k) for k in keys]
    with mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(data, models)) as pool:
        out = []
        for i, r in enumerate(pool.imap(_run_one, keys, chunksize=8), 1):
            out.append(r)
            if i % 500 == 0:
                log.info("прогнозов %d/%d", i, len(keys))
        return out


def attach_facts(res: list[dict], panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """origins: по строке на точку (прогноз + правда); daily: по строке на (точка, календарный день)."""
    by_c = {cid: g.set_index("date") for cid, g in panel.groupby("company_id")}
    wd = all_working_days()
    rows, daily = [], []
    for r in res:
        base = {k: r[k] for k in ("company_id", "as_of", "error")}
        if r["error"]:
            rows.append(base)
            continue
        g = by_c[r["company_id"]]
        a = r["as_of"]
        hist = g[g.index <= a]
        fut = g[(g.index > a) & (g.index <= a + pd.Timedelta(days=HORIZON_DAYS))]
        b0, scale = float(hist["balance_eod"].iloc[-1]), float(hist["scale"].iloc[-1])
        valid = len(fut) > 0 and not fut["gap_in_data"].any()
        cf = fut["balance_eod"] - fut["rescue_in"].cumsum()
        prev = hist["balance_eod"].iloc[-TREND_WD - 1] if len(hist) > TREND_WD else hist["balance_eod"].iloc[0]
        trend = (b0 - prev) / min(TREND_WD, max(len(hist) - 1, 1))
        wd_ahead = np.arange(1, len(fut) + 1)
        trend_path = b0 + trend * wd_ahead
        rows.append({**base, "status": r["status"], "start": "already_negative" if b0 < 0 else "positive",
                     "valid": valid, "scale": scale, "b0": b0, "history_days": len(hist), "prob_raw": r["prob_raw"], "prob_cal": r["prob_cal"],
                     "pred_gap": r["status"] == "gap_expected", "pred_date": r["pred_date"], "max_p_day": r["max_p_day"],
                     "true_counterfactual": bool((cf < 0).any()), "true_strict": bool((fut["balance_eod"] < 0).any()),
                     "true_date_counterfactual": cf.index[np.argmax(cf.to_numpy() < 0)] if (cf < 0).any() else pd.NaT,
                     "trend_gap": bool((trend_path < 0).any()), "trend_score": float(-trend_path.min() / scale),
                     "low_balance_score": -b0 / scale, "seconds": r["seconds"]})
        fact = g["balance_eod"]
        dow = pd.Series(dict(r["dow"]), dtype=float)
        flow = b0 + (g["cum_y"] - float(hist["cum_y"].iloc[-1]))   # операционный факт: без своих переводов,
        for d, p10, p50, p90 in r["daily"]:                      # денег учредителя и разовых — как в backtest
            k = (pd.Timestamp(d) - a).days
            i = int(fact.index.searchsorted(pd.Timestamp(d), side="right")) - 1
            j = int(dow.index.searchsorted(pd.Timestamp(d), side="right")) - 1
            daily.append((r["company_id"], a, k, pd.Timestamp(d), p10, p50, p90, float(fact.iloc[i]),
                          float(flow.iloc[i]), b0, float(dow.iloc[j]) if j >= 0 else b0,
                          b0 + trend * int(wd.searchsorted(pd.Timestamp(d), side="right") - wd.searchsorted(a, side="right")),
                          scale))
    origins = pd.DataFrame(rows)
    daily = pd.DataFrame(daily, columns=["company_id", "as_of", "day", "date", "p10", "p50", "p90", "fact",
                                         "fact_flow", "zero", "dow_mean", "trend", "scale"])
    return origins, daily


# ───────────────────────────── метрики ─────────────────────────────

def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos, n = int(y.sum()), len(y)
    if pos in (0, n):
        return np.nan
    r = pd.Series(score).rank().to_numpy()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (n - pos)))


def ece(p: np.ndarray, y: np.ndarray) -> float:
    r = reliability(p, y, ECE_BINS)
    return float((r["n"] * (r["prob_mean"] - r["fact_rate"]).abs()).sum() / r["n"].sum()) if len(r) else np.nan


def classification(o: pd.DataFrame, label: str) -> pd.DataFrame:
    """Строка на «предсказатель»: v2 (статус + вероятность МК) и бейзлайны."""
    y = o[f"true_{label}"].to_numpy(dtype=bool)
    rows = []

    def one(name: str, pred: np.ndarray | None, score: np.ndarray | None, prob: np.ndarray | None) -> dict:
        r = {"label": label, "predictor": name, "n": len(y), "true_gaps": int(y.sum())}
        if pred is not None:
            tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
            fn, tn = int((~pred & y).sum()), int((~pred & ~y).sum())
            prec = tp / (tp + fp) if tp + fp else np.nan
            rec = tp / (tp + fn) if tp + fn else np.nan
            r.update(tp=tp, fp=fp, fn=fn, tn=tn, accuracy=(tp + tn) / len(y), precision=prec, recall=rec,
                     f1=2 * prec * rec / (prec + rec) if prec + rec > 0 else np.nan)
        if score is not None:
            r["roc_auc"] = auc(score, y.astype(int))
        if prob is not None:
            r["brier"] = float(np.mean((prob - y) ** 2))
            r["ece"] = ece(prob, y.astype(float))
        return r

    pred = o["pred_gap"].to_numpy(dtype=bool)
    cal = o["prob_cal"].to_numpy()
    rows.append(one(PRODUCT, pred, cal, cal))
    rows.append(one(OLD, o["max_p_day"].to_numpy() >= OLD_THRESHOLD, cal, cal))
    rows.append(one("v2: сырая доля траекторий МК", None, o["prob_raw"].to_numpy(), o["prob_raw"].to_numpy()))
    rows.append(one("остаток не меняется", np.zeros(len(y), dtype=bool), None, None))
    rows.append(one("тренд 60 р.д.", o["trend_gap"].to_numpy(dtype=bool), o["trend_score"].to_numpy(), None))
    rows.append(one("низкий остаток (только AUC)", None, o["low_balance_score"].to_numpy(), None))
    rows.append(one("климатология (знает долю разрывов)", None, None, np.full(len(y), y.mean())))
    return pd.DataFrame(rows)


FACTS = {"fact": "фактический остаток", "fact_flow": "операционный (как в backtest)"}


BALANCE_PREDICTORS = {"v2 P50": "p50", "остаток не меняется": "zero", "dow_mean": "dow_mean"}


def regression(d: pd.DataFrame) -> pd.DataFrame:
    """fact — остаток из выписки; fact_flow — остаток без своих переводов, денег учредителя и разовых
    операций (их модель сознательно не прогнозирует) — сравним с nmae_bal в backtest.
    MAE/MSE/RMSE считаются по каждой компании (по её точкам), затем среднее и медиана по компаниям:
    среднее определяют крупные компании, медиана — типичная. В оборотах — ошибка / дневной оборот компании."""
    rows = []
    for fact, day in ((f, day) for f in FACTS for day in REPORT_DAYS):
        g = d[d["day"] == day]
        for name, col in BALANCE_PREDICTORS.items():
            e = (g[col] - g[fact]).rename("e")
            per = pd.DataFrame({"company_id": g["company_id"], "ae": e.abs(), "se": e ** 2,
                                "nae": e.abs() / g["scale"], "nse": (e / g["scale"]) ** 2})
            c = per.groupby("company_id").agg(mae=("ae", "mean"), mse=("se", "mean"), nmae=("nae", "mean"),
                                              nmse=("nse", "mean"))
            c["rmse"], c["nrmse"] = np.sqrt(c["mse"]), np.sqrt(c["nmse"])
            rows.append({"fact": FACTS[fact], "day": day, "predictor": name, "n": len(g), "companies": len(c),
                         **{f"{m}_{agg}": getattr(c[m], agg)() for m in ("mae", "mse", "rmse", "nmae", "nrmse")
                            for agg in ("mean", "median")},
                         "coverage_p10_p90": ((g[fact] >= g["p10"]) & (g[fact] <= g["p90"])).mean()
                         if col == "p50" else np.nan})
    return pd.DataFrame(rows)


# ───────────────────────────── графики ─────────────────────────────

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ml.evaluation.figures import _style
    _style()
    return plt


def fig_reliability(o: pd.DataFrame, path: Path) -> pd.DataFrame:
    from ml.evaluation.figures import GRID, INK_2, MUTED, SURFACE
    plt = _plt()
    y = o["true_counterfactual"].to_numpy(dtype=float)
    rel = pd.concat([reliability(o[c].to_numpy(), y, ECE_BINS).assign(prob=n) for n, c in PROBS.items()])
    fig, ax = plt.subplots(figsize=(5.6, 4.8), facecolor=SURFACE)
    ax.plot([0, 1], [0, 1], color=GRID, lw=1.5)
    style = {"mc_raw": (MUTED, "--", "МК, сырая доля траекторий"), "mc_cal": ("#2a78d6", "-", "МК + isotonic (в ответе)")}
    for name, (c, ls, lab) in style.items():
        r = rel[rel["prob"] == name]
        ax.plot(r["prob_mean"], r["fact_rate"], color=c, ls=ls, lw=2, label=lab, zorder=3)
        ax.scatter(r["prob_mean"], r["fact_rate"], s=np.clip(r["n"], 12, 160), color=c, edgecolor=SURFACE,
                   linewidth=2, zorder=4)
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Предсказанная вероятность разрыва за 30 дней",
           ylabel="Доля точек с разрывом (CF)")
    ax.set_title("Надёжность вероятности; размер — число точек", color=INK_2, loc="left", fontsize=10)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return rel


def fig_confusion(cls: pd.DataFrame, path: Path) -> None:
    from ml.evaluation.figures import INK, INK_2, SURFACE
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), facecolor=SURFACE)
    for ax, label in zip(axes, LABELS):
        r = cls[(cls["label"] == label) & (cls["predictor"] == PRODUCT)].iloc[0]
        m = np.array([[r["tn"], r["fp"]], [r["fn"], r["tp"]]], dtype=float)
        ax.imshow(m / m.sum(), cmap="Blues", vmin=0, vmax=1)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{int(m[i, j])}", ha="center", va="center", fontsize=14,
                        color="white" if m[i, j] / m.sum() > 0.5 else INK)
        ax.set_xticks([0, 1], ["нет разрыва", "разрыв"])
        ax.set_yticks([0, 1], ["нет разрыва", "разрыв"])
        ax.set(xlabel=f"Прогноз (gap_expected, порог {THRESHOLD:.2f})".replace(".", ","), ylabel="Факт за 30 дней")
        ax.grid(False)
        ax.set_title({"counterfactual": "CF: без спасающих поступлений", "strict": "strict: фактический минус"}[label],
                     color=INK_2, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def pick_examples(o: pd.DataFrame, d: pd.DataFrame) -> list[tuple[str, str, pd.Timestamp]]:
    """Три точки разных компаний: верная тревога (максимальная вероятность), пропущенный разрыв, спокойный
    месяц с ошибкой d30, близкой к медианной. Выбор детерминированный."""
    ok = o[(o["start"] == "positive") & o["valid"]]
    used: set[str] = set()
    out = []
    err30 = d[d["day"] == HORIZON_DAYS].assign(e=lambda x: (x["p50"] - x["fact"]).abs() / x["scale"])
    ok = ok.merge(err30[["company_id", "as_of", "e"]], on=["company_id", "as_of"], how="left")
    cands = [
        ("Верная тревога", ok[ok["pred_gap"] & ok["true_counterfactual"]].sort_values(["prob_cal", "company_id"],
                                                                                      ascending=[False, True])),
        ("Пропущенный разрыв", ok[~ok["pred_gap"] & ok["true_counterfactual"]].sort_values(["prob_cal", "company_id"],
                                                                                          ascending=[False, True])),
        ("Спокойный месяц", ok[~ok["pred_gap"] & ~ok["true_counterfactual"]].assign(
            dist=lambda x: (x["e"] - x["e"].median()).abs()).sort_values(["dist", "company_id"])),
    ]
    for title, c in cands:
        c = c[~c["company_id"].isin(used)]
        if len(c):
            used.add(c["company_id"].iloc[0])
            out.append((title, c["company_id"].iloc[0], c["as_of"].iloc[0]))
    return out


def fig_examples(examples, o: pd.DataFrame, d: pd.DataFrame, panel: pd.DataFrame, path: Path) -> None:
    from ml.evaluation.figures import BAND, INK, INK_2, MUTED, SURFACE
    plt = _plt()
    import matplotlib.dates as mdates
    fig, axes = plt.subplots(1, len(examples), figsize=(5.4 * len(examples), 4.2), facecolor=SURFACE, squeeze=False)
    for ax, (title, cid, a) in zip(axes[0], examples):
        g = d[(d["company_id"] == cid) & (d["as_of"] == a)]
        p = panel[(panel["company_id"] == cid) & (panel["date"] > a - pd.Timedelta(days=30))
                  & (panel["date"] <= a + pd.Timedelta(days=HORIZON_DAYS))]
        r = o[(o["company_id"] == cid) & (o["as_of"] == a)].iloc[0]
        k = 1e3
        ax.fill_between(g["date"], g["p10"] / k, g["p90"] / k, color=BAND, lw=0, label="P10–P90")
        ax.plot(g["date"], g["p50"] / k, color="#2a78d6", lw=2, label="P50")
        ax.plot(p["date"], p["balance_eod"] / k, color=INK, lw=1.5, label="Факт")
        after = p[p["date"] > a]
        cf = after["balance_eod"] - after["rescue_in"].cumsum()
        if (cf != after["balance_eod"]).any():   # владелец закрывал дыру своими деньгами — что было бы без них
            ax.plot(after["date"], cf / k, color="#eb6834", lw=1.5, ls="--", label="Факт без своих денег (CF)")
        ax.axhline(0, color=MUTED, lw=1)
        ax.axvline(a, color=MUTED, lw=1, ls=":")
        ax.set_title(f"{title}: {cid}, {a:%d.%m.%Y}\nвероятность {r['prob_cal']:.0%}, статус {r['status']}",
                     color=INK_2, loc="left", fontsize=10)
        ax.set_ylabel("Остаток, тыс. ₽")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes[0][0].legend(frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ───────────────────────────── summary.md ─────────────────────────────

def _fmt(v, nd=3) -> str:
    if v is None or v is pd.NA or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.{nd}f}".replace(",", " ").replace(".", ",")


def md_table(df: pd.DataFrame, cols: dict[str, str], nd: dict[str, int] | None = None) -> str:
    nd = nd or {}
    head = "| " + " | ".join(cols.values()) + " |\n|" + "---|" * len(cols) + "\n"
    body = "".join("| " + " | ".join(v if isinstance(v := r[c], str) else _fmt(v, nd.get(c, 3)) for c in cols) + " |\n"
                   for _, r in df.iterrows())
    return head + body


def experiments_block(reports: Path) -> str:
    """Блок по заданию: AUC МК против hazard, isotonic (ECE до/после), оракулы, отвергнутые эксперименты."""
    out = ["## Эксперименты (backtest, не контрольный датасет)\n"]
    hz = reports / "hazard.csv"
    if hz.exists():
        h = pd.read_csv(hz)
        h = h[h["period"] == "report"].pivot_table(index="company_set", columns="prob", values=["auc", "ece", "brier"])
        out.append("### Вероятность разрыва: МК против модели выживаемости (8.6), period=report\n")
        rows = [{"Набор": {"new_dates": "новые даты", "new_companies": "холдаут"}[cs],
                 "AUC МК": h.loc[cs, ("auc", "mc_cal")], "AUC hazard": h.loc[cs, ("auc", "hazard")],
                 "Brier МК+isotonic": h.loc[cs, ("brier", "mc_cal")], "Brier hazard": h.loc[cs, ("brier", "hazard")],
                 "ECE МК сырой": h.loc[cs, ("ece", "mc_raw")], "ECE МК+isotonic": h.loc[cs, ("ece", "mc_cal")],
                 "ECE hazard": h.loc[cs, ("ece", "hazard")]} for cs in ("new_dates", "new_companies") if cs in h.index]
        df = pd.DataFrame(rows)
        out.append(md_table(df, {c: c for c in df.columns}))
        out.append("\nhazard различает чуть лучше (AUC), но занижает вероятность; калиброванный МК надёжнее по Brier "
                   "и ECE — в продукте остаётся МК + isotonic. Isotonic по CF-метке на tune-фолдах снижает ECE "
                   "сырой доли траекторий примерно в 2–2,5 раза.\n")
    orc = reports / "oracle.csv"
    if orc.exists():
        o = pd.read_csv(orc)
        o = o[(o["period"] == "report") & (o["company_set"] == "new_dates")]
        names = {"v2": "v2 (как есть)", "O1": "O1: нерегулярная часть = факт", "O2": "O2: события = факт",
                 "O3": "O3: даты поступлений = факт"}
        o = o.assign(row=o["row"].map(names))
        out.append("\n### Оракулы (8.0): потолок, если одна часть прогноза идеальна; report, новые даты\n")
        out.append(md_table(o, {"row": "Вариант", "nmae_bal_d7": "nMAE d7", "nmae_bal_d30": "nMAE d30",
                                "counterfactual_precision": "CF P", "counterfactual_recall": "CF R",
                                "coverage_p10_p90": "Покрытие P10–P90"}, {"nmae_bal_d7": 2, "nmae_bal_d30": 2,
                                                                          "counterfactual_precision": 2,
                                                                          "counterfactual_recall": 2,
                                                                          "coverage_p10_p90": 2}))
        out.append("\nПотолок — нерегулярная часть (O1): точные события (O2) и даты поступлений (O3) почти ничего "
                   "не дают.\n")
    out.append("\n### Отвергнутые эксперименты (решение по tune, CF recall при CF precision ≥ 0,45)\n")
    out.append("| Эксперимент | Почему не включён |\n|---|---|\n")
    out.append("| 8.1 признаки остатка (+ last_year) | CF recall на tune упал: 0,685 → 0,646 |\n")
    out.append("| Перенос просроченных поступлений клиентов в прогноз | recall на tune вырос (0,685 → 0,748), но "
               "остаток d7 хуже на 7% (1,83 → 1,95), на report recall +1 п.п. при d7 +8% — флаг выключен |\n")
    out.append("| 8.5 v2_cf (переносы обязательных платежей на нормальные даты) | CF recall на tune не изменился "
               "(0,685), меняются только даты событий у 21% точек |\n")
    ly = _last_year_line(reports)
    if ly:
        out.append(ly)
    return "".join(out)


def _last_year_line(reports: Path) -> str | None:
    p = reports / "experiments.csv"
    if not p.exists():
        return None
    t = pd.read_csv(p)
    t = t[(t["period"] == "tune") & (t["company_set"] == "new_dates")].set_index("row")
    if "last_year" not in t.index:
        return None
    b, ly = t.loc["base"], t.loc["last_year"]
    up = ly["counterfactual_recall"] > b["counterfactual_recall"] and ly["counterfactual_precision"] >= 0.45
    verdict = "прошёл" if up else "не включён"
    return (f"| 8.2 last_year без признаков остатка | {verdict}: CF recall на tune {_fmt(b['counterfactual_recall'])} → "
            f"{_fmt(ly['counterfactual_recall'])}, precision {_fmt(ly['counterfactual_precision'])} |\n")


JURY_COLS = {"accuracy": "Accuracy", "precision": "Precision", "recall": "Recall", "f1": "F1",
             "roc_auc": "ROC-AUC", "brier": "Brier"}
LABEL_NAMES = {"counterfactual": "CF (без своих денег)", "strict": "strict (фактический минус)"}


def jury_block(cls: pd.DataFrame, segments) -> str:
    """Первый блок: ровно метрики жюри и матрица ошибок в абсолютных числах — продуктовая v2."""
    seg_names = {"all": "все данные", "holdout": "холдаут компаний", "seen": "компании из обучения"}
    keep = [seg for seg, _ in segments if seg in ("all", "holdout")]
    rows = cls[(cls["predictor"] == PRODUCT) & cls["segment"].isin(keep)].copy()
    rows["order"] = rows["label"].map({lab: i for i, lab in enumerate(LABELS)}) * 10 + rows["segment"].map(
        {seg: i for i, seg in enumerate(keep)})
    rows = rows.sort_values("order").assign(
        what=lambda x: x["label"].map(LABEL_NAMES) + ", " + x["segment"].map(seg_names))
    out = [f"## Главное: разрыв в ближайшие 30 дней — {PRODUCT}\n\n",
           md_table(rows, {"what": "Метка, данные", "n": "Точек", **JURY_COLS}),
           "\nМатрица ошибок, абсолютные числа (прогноз — статус `gap_expected`):\n\n",
           md_table(rows, {"what": "Метка, данные", "tp": "TP", "fp": "FP", "fn": "FN", "tn": "TN"}),
           "\nTP — разрыв предсказан и был; FP — ложная тревога; FN — пропущенный разрыв; TN — верно «спокойно». "
           "CF — основная метка продукта: минус, который был бы без денег владельца (переводов из другого банка и "
           "займов учредителя); strict — фактический минус на счёте. Вероятность (ROC-AUC, Brier) — откалиброванная "
           "под CF, поэтому Brier для strict выше, чем у константы «доля разрывов» (см. подробные таблицы).\n\n"]
    return "".join(out)


def threshold_block(cls: pd.DataFrame, segments, reports: Path, out: Path) -> str:
    s = [f"## Порог тревоги: {OLD_THRESHOLD:.2f} → {THRESHOLD:.2f}\n\n".replace(".", ",")]
    choice = reports / "threshold_choice.csv"
    if choice.exists():
        c = pd.read_csv(choice)
        s.append("Подбор в backtest (`python -m ml.evaluation.threshold`): порог доли траекторий ниже нуля в день, "
                 "максимум F1 по CF строго на tune-фолдах (новые даты), затем без изменений — report и холдаут:\n\n")
        s.append(md_table(c, {"set": "Набор", "threshold": "Порог", "precision": "Precision", "recall": "Recall",
                              "f1": "F1", "tp": "TP", "fp": "FP", "fn": "FN", "tn": "TN"}, {"threshold": 2}))
        fig = reports / "figures" / "threshold.png"
        if fig.exists():
            shutil.copy(fig, out / "figures" / "threshold.png")
            s.append("\n![F1 от порога](figures/threshold.png)\n")
    rows = cls[cls["predictor"].isin([PRODUCT, OLD]) & (cls["label"] == "counterfactual")
               & cls["segment"].isin([seg for seg, _ in segments])]
    s.append("\nНа этом датасете (CF):\n\n")
    seg_names = {"all": "все данные", "holdout": "холдаут", "seen": "компании из обучения"}
    s.append(md_table(rows.assign(seg=rows["segment"].map(seg_names)), {"seg": "Данные", "predictor": "Вариант", "precision": "Precision",
                                                         "recall": "Recall", "f1": "F1", "tp": "TP", "fp": "FP",
                                                         "fn": "FN", "tn": "TN"}))
    s.append("\nПорог меняет только статус и дату разрыва; вероятность, коридор и суммы те же.\n\n")
    return "".join(s)


def balance_block(reg: pd.DataFrame) -> str:
    s = ["## Ошибка остатка P50 по горизонтам\n\n"
         "Ошибка считается по каждой компании (по всем её точкам), затем среднее и медиана по компаниям. "
         "Среднее в рублях определяют несколько крупных компаний, медиана — типичная компания; в оборотах — "
         "ошибка, делённая на средний дневной оборот компании (сравнимо между компаниями).\n\n"]
    cols_rub = {"day": "Дней", "predictor": "Прогноз", "mae_mean": "MAE ср., ₽", "mae_median": "MAE мед., ₽",
                "mse_mean": "MSE ср., ₽²", "mse_median": "MSE мед., ₽²", "rmse_mean": "RMSE ср., ₽",
                "rmse_median": "RMSE мед., ₽", "nmae_mean": "MAE, оборотов (ср.)", "nmae_median": "MAE, оборотов (мед.)",
                "nrmse_mean": "RMSE, оборотов (ср.)", "coverage_p10_p90": "P10–P90"}
    nd = {"mae_mean": 0, "mae_median": 0, "mse_mean": 0, "mse_median": 0, "rmse_mean": 0, "rmse_median": 0,
          "nmae_mean": 2, "nmae_median": 2, "nrmse_mean": 2, "coverage_p10_p90": 2}
    for fact, title in ((FACTS["fact"], "Против фактического остатка из выписки"),
                        (FACTS["fact_flow"], "Против операционного остатка (без своих переводов, денег учредителя и "
                                             "разовых операций — как nMAE в backtest)")):
        s.append(f"### {title}\n\n" + md_table(reg[reg["fact"] == fact], cols_rub, nd) + "\n")
    s.append(
        "**Почему на фактическом остатке «остаток не меняется» на 30 дней точнее и почему он от этого не полезнее.** "
        "На 30 днях против фактического остатка наивный прогноз выигрывает у P50 по медиане компаний и в оборотах "
        "(по среднему в рублях — примерно вровень). Фактический остаток включает переводы своих средств из другого банка и деньги учредителя: когда денег "
        "мало, владелец сам доливает счёт, когда много — выводит. Остаток через месяц поэтому часто возвращается "
        "к привычному уровню, и константа «как сегодня» попадает близко. Модель сознательно не прогнозирует эти "
        "переводы — это реакция владельца на нехватку, а не денежный поток бизнеса, и именно эту нехватку мы "
        "должны показать заранее. На операционном остатке (без этих переводов) P50 точнее наивного на 7–30 днях. "
        "А для задачи продукта наивный прогноз бесполезен: остаток у него не меняется, поэтому он никогда не "
        "предсказывает разрыв — recall 0 по обеим меткам (строка «остаток не меняется» в подробных таблицах), "
        "все разрывы пропущены. На 1 день наивный тоже точнее, так же и в backtest (nMAE d1 0,95 против 0,97): "
        "точки здесь — конец месяца, и модель на следующий день ждёт поступлений, которые часто приходят позже.\n\n")
    return "".join(s)


def write_summary(out: Path, meta: dict, o: pd.DataFrame, cls: pd.DataFrame, reg: pd.DataFrame,
                  examples, reports: Path, steps: list[str], shown: tuple[str, pd.Timestamp] | None) -> None:
    cls_cols = {"predictor": "Предсказатель", "true_gaps": "Разрывов", "accuracy": "Accuracy", "precision": "Precision",
                "recall": "Recall", "f1": "F1", "roc_auc": "ROC-AUC", "brier": "Brier", "ece": "ECE"}
    s = [f"# Контрольный датасет: отчёт v2\n\n",
         jury_block(cls, meta["segments"]),
         f"## Данные и время\n\n"
         f"- Данные: `{meta['data']}` — компаний {meta['companies']}, операций {_fmt(meta['operations'])}, "
         f"{meta['date_min']} … {meta['date_max']}.\n"
         f"- Модель: `{meta['model_version']}`, обучена до {meta['trained_until']}. {meta['sample_note']}\n"
         f"- Точки прогноза: последний рабочий день месяца с 30 днями факта после — {meta['origins']}; "
         f"прогноз построен для {meta['forecasts']}, счёт закрыт — {meta['closed']}, другие отказы — "
         f"{meta['errors']}; с пропуском данных на горизонте (не оцениваются) — {meta['invalid']}; "
         f"остаток уже < 0 на дату прогноза (отдельно) — {meta['already_negative']}.\n"
         f"- **Время на полном датасете: {_fmt(meta['total_min'], 1)} мин** (цель ≤ 15): загрузка {meta['load_s']:.0f} с, "
         f"прогнозы {meta['forecast_s']:.0f} с ({meta['workers']} процессов, {_fmt(meta['per_forecast_s'], 2)} с на прогноз), "
         f"метрики и графики {meta['report_s']:.0f} с.\n\n",
         threshold_block(cls, meta["segments"], reports, out),
         balance_block(reg)]
    if steps:
        cid, a = shown
        s.append(f"## Как посчитано: один прогноз по шагам ({cid} на {a:%d.%m.%Y})\n\n"
                 "То же поле `trace` в ответе сервиса (вкладка «Как посчитано»). Время каждого шага — в мс; "
                 "рублёвые суммы есть в JSON, в лог не пишутся.\n\n```\n" + "\n".join(steps) + "\n```\n\n")
    s.append("## Подробно: разрывы, все предсказатели и бейзлайны\n\n")
    for label, title in (("counterfactual", "Метка CF"), ("strict", "Метка strict")):
        for seg, seg_title in meta["segments"]:
            c = cls[(cls["label"] == label) & (cls["segment"] == seg)]
            if not c.empty:
                s.append(f"### {title} — {seg_title}\n\n" + md_table(c, cls_cols) + "\n")
    s.append("Precision/recall/F1/accuracy — по статусу `gap_expected`. «Сырая доля траекторий» — вероятность до "
             "isotonic, у неё только ROC-AUC, Brier и ECE. «Климатология» знает долю разрывов в этом же наборе — "
             "нижняя граница Brier, а не честный соперник. Вероятность в ответе калибрована под CF-метку (её "
             "разрывов в ~8 раз больше, чем фактических минусов), поэтому для strict Brier и ECE хуже "
             "климатологии: для strict смотреть на recall и ROC-AUC.\n\n")
    s.append("![Матрицы ошибок](figures/confusion.png)\n\n## Надёжность вероятности\n\n"
             "![Reliability](figures/reliability.png)\n\n## Примеры компаний\n\n![Примеры](figures/examples.png)\n\n")
    for title, cid, a in examples:
        r = o[(o["company_id"] == cid) & (o["as_of"] == a)].iloc[0]
        s.append(f"- **{title}** — {cid} на {a:%d.%m.%Y}: статус `{r['status']}`, вероятность {r['prob_cal']:.0%}, "
                 f"CF-разрыв в факте: {'да' if r['true_counterfactual'] else 'нет'}.\n")
    s.append("\n" + experiments_block(reports))
    (out / "summary.md").write_text("".join(s), encoding="utf-8")


def show_steps(ctx: ForecastContext, cid: str, as_of: pd.Timestamp) -> list[str]:
    """Пошаговый лог одного прогноза (с советами, как у предпринимателя) — для экрана и run.log."""
    forecast(cid, as_of.date(), HORIZON_DAYS, seed=42, context=ctx)      # прогрев: первый вызов дольше
    r = forecast(cid, as_of.date(), HORIZON_DAYS, seed=42, context=ctx)
    return [f"{cid} на {as_of:%d.%m.%Y}: статус {r.status}"] + format_steps(r.trace)


# ───────────────────────────── main ─────────────────────────────

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--models", default="models")
    ap.add_argument("--reports", default="reports", help="откуда брать результаты экспериментов для summary.md")
    ap.add_argument("--out", default="reports/control")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="только первые N компаний (отладка)")
    ap.add_argument("--show", default=None, help="компания для пошагового лога (по умолчанию — «верная тревога»)")
    ap.add_argument("--show-as-of", default=None, help="дата для --show (по умолчанию — последняя точка компании)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(out / "run.log", mode="w", encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), fh])
    logging.getLogger("categorizer").setLevel(logging.WARNING)
    t0 = time.perf_counter()

    ctx = ForecastContext.load(args.data, args.models, "reports/backtest_residuals.parquet")
    t_load = time.perf_counter() - t0
    panel = ctx.panel
    origins = month_origins(panel)
    if args.limit:
        keep = sorted(origins["company_id"].unique())[:args.limit]
        origins = origins[origins["company_id"].isin(keep)]
    log.info("контекст загружен за %.0f с: компаний %d, точек прогноза %d", t_load, panel["company_id"].nunique(),
             len(origins))
    t1 = time.perf_counter()
    res = run_forecasts(ctx, origins, args.workers, args.data, args.models)
    t_fc = time.perf_counter() - t1
    log.info("прогнозы: %d за %.0f с", len(res), t_fc)

    t2 = time.perf_counter()
    o, d = attach_facts(res, panel)
    model_dir = Path(args.models) / ctx.model_version
    training = json.loads((model_dir / "training.json").read_text(encoding="utf-8"))
    holdout = set(training.get("holdout_companies", []))
    same_data = Path(args.data).resolve() == Path(DEFAULT_DATA).resolve()
    o["segment_holdout"] = o["company_id"].isin(holdout) if same_data else False
    ok = o[o["error"].isna()].astype({"valid": bool, "pred_gap": bool, "true_counterfactual": bool,
                                       "true_strict": bool, "trend_gap": bool})
    evaluated = ok[ok["valid"] & (ok["start"] == "positive")]
    segments = [("all", "все точки")]
    if same_data:
        segments += [("holdout", "холдаут компаний (модель их не видела)"), ("seen", "компании из обучения")]
    parts = []
    for label in LABELS:
        for seg, _ in segments:
            sub = evaluated if seg == "all" else evaluated[evaluated["segment_holdout"] == (seg == "holdout")]
            if len(sub):
                parts.append(classification(sub, label).assign(segment=seg))
    cls = pd.concat(parts, ignore_index=True).astype({c: "Int64" for c in ("n", "true_gaps", "tp", "fp", "fn", "tn")})
    d_eval = d.merge(ok.loc[ok["valid"], ["company_id", "as_of"]], on=["company_id", "as_of"])
    reg = regression(d_eval)
    cls.to_csv(out / "metrics_gaps.csv", index=False)
    reg.to_csv(out / "metrics_balance.csv", index=False)
    o.drop(columns=[c for c in ("b0",) if c in o]).to_parquet(out / "origins.parquet", index=False)
    d_eval.to_parquet(out / "daily.parquet", index=False)
    rel = fig_reliability(evaluated, out / "figures" / "reliability.png")
    rel.assign(bin=rel["bin"].astype(str)).to_csv(out / "reliability.csv", index=False)
    fig_confusion(cls[cls["segment"] == "all"], out / "figures" / "confusion.png")
    examples = pick_examples(evaluated, d_eval)
    fig_examples(examples, o, d_eval, panel, out / "figures" / "examples.png")
    shown = None
    if args.show:
        dates = ok.loc[ok["company_id"] == args.show, "as_of"]
        shown = (args.show, pd.Timestamp(args.show_as_of) if args.show_as_of else dates.max())
    else:   # верная тревога с самой длинной историей — на экране видны все шаги
        alarms = evaluated[evaluated["pred_gap"] & evaluated["true_counterfactual"]]
        if len(alarms):
            r = alarms.sort_values(["history_days", "prob_cal", "company_id"], ascending=[False, False, True]).iloc[0]
            shown = (r["company_id"], r["as_of"])
    steps = show_steps(ctx, *shown) if shown else []
    for line in steps:
        log.info("trace | %s", line)
    t_rep = time.perf_counter() - t2

    n_fc = int(ok.shape[0])
    meta = {
        "data": args.data, "companies": int(ctx.companies["company_id"].nunique()),
        "operations": int((~ctx.ops["is_duplicate"]).sum()),
        "date_min": f"{ctx.ops['operation_date'].min():%d.%m.%Y}", "date_max": f"{ctx.ops['operation_date'].max():%d.%m.%Y}",
        "model_version": ctx.model_version, "trained_until": training.get("trained_until", "?"),
        "sample_note": ("Это датасет участников: модель видела все его даты, метрики in-sample, кроме холдаута "
                        f"компаний ({len(holdout)} шт.). Честные out-of-time цифры — backtest, блок ниже и "
                        "reports/experiments.csv." if same_data else
                        f"Если в этих данных те же компании и даты, что в обучении (до {training.get('trained_until', '?')}), "
                        "метрики in-sample; на новых компаниях или датах после обучения — честная проверка."),
        "origins": len(origins), "forecasts": n_fc, "closed": int((o["error"] == "closed").sum()),
        "errors": int((o["error"] == "forecast_error").sum()), "invalid": int((~ok["valid"]).sum()),
        "already_negative": int((ok["valid"] & (ok["start"] == "already_negative")).sum()),
        "load_s": t_load, "forecast_s": t_fc, "report_s": t_rep, "workers": args.workers,
        "per_forecast_s": float(ok["seconds"].mean()) if n_fc else np.nan,
        "total_min": (time.perf_counter() - t0) / 60, "segments": segments,
    }
    write_summary(out, meta, o, cls, reg, examples, Path(args.reports), steps, shown)
    log.info("разрывы (CF, все точки):\n%s", cls[(cls["label"] == "counterfactual") & (cls["segment"] == "all")]
             [["predictor", "n", "true_gaps", "precision", "recall", "f1", "roc_auc", "brier", "ece"]]
             .to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    log.info("остаток, ошибка в оборотах (медиана по компаниям):\n%s",
             reg[["fact", "day", "predictor", "nmae_median", "nmae_mean", "coverage_p10_p90"]]
             .to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    log.info("готово за %.1f мин, отчёт: %s", meta["total_min"], out / "summary.md")


if __name__ == "__main__":
    main()
