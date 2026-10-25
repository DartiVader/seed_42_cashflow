"""Метрики кассовых разрывов в backtest: precision, recall, упреждение, ошибки даты и суммы, Brier, покрытие.

Для каждой точки прогноза (компания, as_of) строим Монте-Карло так же, как в forecast():
прогноз остатка модели + траектории ошибок из пула. Пул — только ошибки с целевой датой ≤ cutoff
фолда, то есть то, что было известно на момент прогноза.

Три метки «правды» (по фактическому balance_eod, с переводами и разовыми операциями):
  strict          — фактический минус: min_k B[a+k] < порога;
  counterfactual  — минус без спасающих поступлений (own_transfer из другого банка + займ/взнос
                    учредителя): min_k (B[a+k] − Σ_{j≤k} rescue_in[a+j]) < порога. Основная для продукта;
                    переносы платежей в выписке не видны, поэтому и она занижает число настоящих разрывов;
  near_miss       — «почти не хватило»: min_k B[a+k] < 1 дневного оборота. Только для объяснения тревог.
Точки, где остаток уже ниже порога на as_of, оцениваются отдельно (start=already_negative).

    python -m ml.evaluation.gap_metrics reports/backtest_predictions.parquet
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.evaluation.calibration import SHORTFALL_KINDS, ShortfallCalibrator, fit_calibrator, fit_log_isotonic, reliability
from ml.forecast.gaps import GapConfig, finalize_shortfall, shortfall_stats
from ml.forecast.montecarlo import ALL, McConfig, pick_pool

log = logging.getLogger(__name__)

LABELS = ("strict", "counterfactual", "near_miss")
AMOUNT_LABELS = ("strict", "counterfactual")
# колонки прогноза суммы: (kind, медиана, P25, P75); факт — true_{kind}_{label}
# порядок как в gaps.SF_QUANTILES: медиана, P10, P90, P25, P75
SF_COLS = {k: (c, f"{c}_p10", f"{c}_p90", f"{c}_p25", f"{c}_p75")
           for k, c in (("at_gap", "pred_sf_gap"), ("total", "pred_shortfall"))}
SF_TRUE = {"at_gap": "true_sf_gap", "total": "true_shortfall"}
HIT_TOL = 0.3
CALIBRATION_LABEL = "counterfactual"


@dataclass(frozen=True)
class GapEvalConfig:
    horizon: int = 21            # рабочих дней ≈ 30 календарных
    threshold: float = 0.0
    p_day_min: float = GapConfig().p_day_min   # как в детекторе
    shortfall_window: int = 5    # рабочих дней от даты разрыва (прогнозной / фактической)
    n_paths: int = 1000
    seed: int = 42


def _pools(df: pd.DataFrame, cutoff: pd.Timestamp, horizon: int) -> dict[str, np.ndarray]:
    """Траектории накопленной ошибки, целиком известные к cutoff."""
    r = df[df["target_date"] <= cutoff]
    wide = r.pivot_table(index=["industry", "company_id", "as_of"], columns="h", values="err_cum_norm",
                         observed=True)
    wide = wide.reindex(columns=range(1, horizon + 1)).dropna()
    pool = {str(ind): g.to_numpy() for ind, g in wide.groupby(level="industry", observed=True)}
    pool[ALL] = wide.to_numpy()
    return pool


def evaluate_origins(bt: pd.DataFrame, model: str, cfg: GapEvalConfig = GapEvalConfig(),
                     mc: McConfig = McConfig()) -> pd.DataFrame:
    """По строке на (компания, as_of): прогноз разрыва, факт по трём меткам, покрытие P10–P90."""
    m = bt[(bt["model"] == model) & (bt["h"] <= cfg.horizon)].copy()
    m["industry"] = m["industry"].astype(str)
    m["err_cum_norm"] = ((m["bal_flow_true"] - m["bal_hat"]) / m["scale"]).where(m["bal_valid"])
    rng = np.random.default_rng(cfg.seed)
    out = []
    for cutoff, fold in m.groupby("cutoff", sort=True):
        pool = _pools(m, cutoff, cfg.horizon)
        if len(pool[ALL]) < mc.min_pool:
            log.info("модель %s, cutoff %s: мало траекторий в пуле (%d) — пропуск", model, cutoff.date(),
                     len(pool[ALL]))
            continue
        for _, g in fold.groupby(["company_id", "as_of"], sort=False):
            if len(g) < cfg.horizon or not g["bal_valid"].all():
                continue   # неполный горизонт или пропуск в данных — правды нет
            out.append(_one(g.sort_values("h"), pick_pool(pool, g["industry"].iloc[0], mc), cfg, rng))
    res = pd.DataFrame(out)
    res.insert(0, "model", model)
    return res


def _one(g: pd.DataFrame, pool: np.ndarray, cfg: GapEvalConfig, rng: np.random.Generator) -> dict:
    scale = float(g["scale"].iloc[0])
    b0 = float(g["bal_asof"].iloc[0])
    paths = g["bal_hat"].to_numpy()[None, :] + pool[rng.integers(len(pool), size=cfg.n_paths)] * scale
    below = paths < cfg.threshold
    p_day = below.mean(axis=0)
    hit = np.flatnonzero(p_day >= cfg.p_day_min)
    failed = below.any(axis=1)

    fact = g["bal_true"].to_numpy()
    q10, q90 = np.percentile(paths, [10, 90], axis=0)
    sf = shortfall_stats(paths, int(hit[0]), cfg.threshold, cfg.shortfall_window) if len(hit) else None
    row = {
        "company_id": g["company_id"].iloc[0], "as_of": g["as_of"].iloc[0],
        "company_set": g["company_set"].iloc[0], "period": g["period"].iloc[0],
        "industry": g["industry"].iloc[0], "scale": scale,
        "start": "already_negative" if b0 < cfg.threshold else "positive",
        "pred_gap": len(hit) > 0,
        "pred_h": int(hit[0]) + 1 if len(hit) else np.nan,
        **{c: (sf[kind][i] if sf else np.nan) for kind, cols in SF_COLS.items() for i, c in enumerate(cols)},
        "probability": float(failed.mean()),
        "max_p_day": float(p_day.max()),   # pred_gap при любом пороге: max_p_day ≥ p_day_min (ml.evaluation.threshold)
        "coverage": float(((fact >= q10) & (fact <= q90)).mean()),
        "coverage_d7": float(q10[4] <= fact[4] <= q90[4]),
        "coverage_d30": float(q10[-1] <= fact[-1] <= q90[-1]),
    }
    truths = {
        "strict": (fact, cfg.threshold),
        "counterfactual": (fact - g["rescue_true"].to_numpy(), cfg.threshold),
        "near_miss": (fact, max(cfg.threshold, scale)),
    }
    for label, (bal, thr) in truths.items():
        t = np.flatnonzero(bal < thr)
        row[f"true_gap_{label}"] = len(t) > 0
        row[f"true_h_{label}"] = int(t[0]) + 1 if len(t) else np.nan
        row[f"true_date_{label}"] = g["target_date"].iloc[t[0]] if len(t) else pd.NaT
        row[f"true_shortfall_{label}"] = float(thr - bal.min()) if len(t) else np.nan
        row[f"true_sf_gap_{label}"] = float(thr - bal[t[0]:t[0] + cfg.shortfall_window].min()) if len(t) else np.nan
    return row


def summarize_gaps(res: pd.DataFrame, by: list[str], prob_col: str = "probability") -> pd.DataFrame:
    """Метрики по группам; по строке на каждую метку правды (колонка label)."""
    parts = []
    for label in LABELS:
        def one(g: pd.DataFrame, label=label) -> pd.Series:
            truth = g[f"true_gap_{label}"].astype(bool)
            tp = g["pred_gap"] & truth
            n_pred, n_true = int(g["pred_gap"].sum()), int(truth.sum())
            t = g[tp]
            dh = t["pred_h"] - t[f"true_h_{label}"]
            sf = t["pred_shortfall"] - t[f"true_shortfall_{label}"]
            return pd.Series({
                "n_origins": len(g), "true_gaps": n_true, "pred_gaps": n_pred,
                "precision": tp.sum() / n_pred if n_pred else np.nan,
                "recall": tp.sum() / n_true if n_true else np.nan,
                # упреждение: календарных дней от прогноза до фактического провала (по пойманным)
                "lead_days_mean": (t[f"true_date_{label}"] - t["as_of"]).dt.days.mean(),
                "date_err_wd_mean": dh.abs().mean(),
                "date_err_wd_bias": dh.mean(),          # < 0 — предупреждаем раньше факта
                "shortfall_rel_err": (sf.abs() / t[f"true_shortfall_{label}"]).median(),
                "brier": ((g[prob_col] - truth) ** 2).mean(),
                "brier_climatology": ((truth.mean() - truth) ** 2).mean(),
                "coverage_p10_p90": g["coverage"].mean(),
                "coverage_d7": g["coverage_d7"].mean(),
                "coverage_d30": g["coverage_d30"].mean(),
            })
        s = res.groupby(by, observed=True).apply(one, include_groups=False).reset_index()
        s.insert(len(by), "label", label)
        parts.append(s)
    return pd.concat(parts, ignore_index=True)


def calibrate(res: pd.DataFrame, label: str = CALIBRATION_LABEL) -> tuple[pd.DataFrame, dict]:
    """Isotonic по каждой модели на period=tune, применение ко всем точкам → probability_cal и суммы *_cal.
    Возвращает {модель: {"probability": Calibrator, "shortfall": ShortfallCalibrator}}."""
    out, calibrators = [], {}
    for model, g in res.groupby("model", sort=False):
        tune = g[g["period"] == "tune"]
        cal = fit_calibrator(tune["probability"].to_numpy(), tune[f"true_gap_{label}"].to_numpy(), label)
        sf_cal = fit_shortfall_calibrator(tune, label)
        calibrators[model] = {"probability": cal, "shortfall": sf_cal}
        g = apply_shortfall_calibrator(g, sf_cal)
        out.append(g.assign(probability_cal=cal(g["probability"].to_numpy())))
    return pd.concat(out, ignore_index=True), calibrators


def fit_shortfall_calibrator(g: pd.DataFrame, label: str = CALIBRATION_LABEL) -> ShortfallCalibrator:
    """По пойманным разрывам tune-фолдов: log(прогноз) → log(факт) для каждой суммы.
    Границы P10/P90 сдвигаются тем же коэффициентом, что и медиана, если на tune это не уменьшает
    долю факта в [P10, P90]."""
    maps, bounds = {}, {}
    for kind, cols in SF_COLS.items():
        c = g[g["pred_gap"] & g[f"true_gap_{label}"]]
        fact = c[f"{SF_TRUE[kind]}_{label}"].to_numpy()
        maps[kind] = fit_log_isotonic(c[cols[0]].to_numpy(), fact)
        q = [c[col].to_numpy() for col in cols]
        shifted = ShortfallCalibrator(maps, {kind: True}, label).apply(kind, *q)
        bounds[kind] = bool(_inside(fact, shifted[1], shifted[2]) >= _inside(fact, q[1], q[2]))
    return ShortfallCalibrator(maps, bounds, label)


def apply_shortfall_calibrator(g: pd.DataFrame, cal: ShortfallCalibrator | None) -> pd.DataFrame:
    """Колонки <pred>_cal; ограничение at_gap ≤ total — как в forecast()."""
    sf = {k: tuple(g[c].to_numpy() for c in cols) for k, cols in SF_COLS.items()}
    out = finalize_shortfall(sf, cal)
    return g.assign(**{f"{c}_cal": out[k][i] for k, cols in SF_COLS.items() for i, c in enumerate(cols)})


def _inside(fact, lo, hi) -> float:
    return float(np.mean((fact >= lo) & (fact <= hi))) if len(fact) else np.nan


def summarize_amounts(res: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Ошибка суммы по пойманным разрывам: для каждой метки, суммы и варианта (raw / cal)."""
    parts = []
    for label in AMOUNT_LABELS:
        caught = res[res["pred_gap"] & res[f"true_gap_{label}"].astype(bool)]
        for kind, cols in SF_COLS.items():
            for variant, suf in (("raw", ""), ("cal", "_cal")):
                def one(g: pd.DataFrame) -> pd.Series:
                    fact = g[f"{SF_TRUE[kind]}_{label}"].to_numpy()
                    pred, p10, p90, p25, p75 = (g[c + suf].to_numpy() for c in cols)
                    err = np.abs(pred - fact)
                    rel = err / fact
                    return pd.Series({
                        "n_caught": len(g), "fact_median": np.median(fact) if len(g) else np.nan,
                        "mae_rub": err.mean(), "mae_scale": (err / g["scale"].to_numpy()).mean(),
                        "median_rel_err": np.median(rel) if len(g) else np.nan,
                        "within_30pct": (rel <= HIT_TOL).mean(), "in_range_p25_p75": _inside(fact, p25, p75),
                        "in_range_p10_p90": _inside(fact, p10, p90),
                        "bias_rel_median": np.median((pred - fact) / fact) if len(g) else np.nan,
                    })
                s = caught.groupby(by, observed=True).apply(one, include_groups=False).reset_index()
                s.insert(len(by), "label", label)
                s.insert(len(by) + 1, "amount", kind)
                s.insert(len(by) + 2, "variant", variant)
                parts.append(s)
    return pd.concat(parts, ignore_index=True)


def reliability_table(res: pd.DataFrame, label: str = CALIBRATION_LABEL) -> pd.DataFrame:
    rep = res[res["period"] == "report"]
    parts = []
    for model, g in rep.groupby("model", sort=False):
        for col in ("probability", "probability_cal"):
            r = reliability(g[col].to_numpy(), g[f"true_gap_{label}"].to_numpy())
            parts.append(r.assign(model=model, prob=col, label=label))
    return pd.concat(parts, ignore_index=True)


def run(bt: pd.DataFrame, models: list[str] | None = None, cfg: GapEvalConfig = GapEvalConfig()) -> pd.DataFrame:
    models = models or sorted(bt["model"].unique())
    return pd.concat([evaluate_origins(bt, m, cfg) for m in models], ignore_index=True)


def write_reports(res: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, dict]:
    res, calibrators = calibrate(res)
    res.to_parquet(out / "gap_origins.parquet", index=False)
    by = ["model", "company_set", "period", "start"]
    summary = summarize_gaps(res, by)
    cal = summarize_gaps(res, by, prob_col="probability_cal")[by + ["label", "brier"]]
    summary = summary.merge(cal.rename(columns={"brier": "brier_calibrated"}), on=by + ["label"])
    summary.to_csv(out / "gap_metrics.csv", index=False)
    reliability_table(res).to_csv(out / "gap_reliability.csv", index=False)
    summarize_amounts(res, by).to_csv(out / "shortfall_metrics.csv", index=False)
    for model, c in calibrators.items():
        c["probability"].save(out / f"calibration_{model}.json")
        c["shortfall"].save(out / f"shortfall_calibration_{model}.json")
    return summary, calibrators


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("predictions")
    ap.add_argument("--models", default=None)
    ap.add_argument("--out", default=None, help="каталог для отчётов (по умолчанию рядом с файлом)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bt = pd.read_parquet(args.predictions)
    res = run(bt, args.models.split(",") if args.models else None)
    out = Path(args.out or Path(args.predictions).parent)
    summary, _ = write_reports(res, out)
    log_summary(summary)
    log_amounts(pd.read_csv(out / "shortfall_metrics.csv"))


def log_summary(summary: pd.DataFrame) -> None:
    rep = summary[(summary["period"] == "report") & (summary["start"] == "positive")]
    cols = ["model", "company_set", "label", "true_gaps", "pred_gaps", "precision", "recall", "lead_days_mean",
            "date_err_wd_mean", "brier", "brier_calibrated", "brier_climatology", "coverage_p10_p90"]
    log.info("разрывы (period=report, start=positive):\n%s",
             rep[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))



def log_amounts(m: pd.DataFrame) -> None:
    rep = m[(m["period"] == "report") & (m["start"] == "positive")]
    cols = ["model", "company_set", "label", "amount", "variant", "n_caught", "mae_rub", "mae_scale",
            "median_rel_err", "within_30pct", "in_range_p10_p90", "in_range_p25_p75"]
    log.info("сумма нехватки (period=report, start=positive):\n%s",
             rep[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
