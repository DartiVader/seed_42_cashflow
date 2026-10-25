"""Метрики прогноза потока и остатка."""
from __future__ import annotations

import numpy as np
import pandas as pd

# рабочие дни ≈ 1 / 7 / 14 / 30 календарных
REPORT_H = {1: "d1", 5: "d7", 10: "d14", 21: "d30"}
WEEK = 5   # рабочих дней в «неделе» для недельного WAPE


def add_balance_paths(df: pd.DataFrame) -> pd.DataFrame:
    """Прогноз остатка = остаток на as_of + накопленный прогноз потока.

    bal_flow_true — «операционный» факт: тот же якорь + фактический поток без own_transfer и
    разовых. Именно его объясняет модель потока; bal_true — фактический остаток со всем остальным.
    """
    df = df.sort_values(["model", "company_id", "as_of", "h"]).reset_index(drop=True)
    net = df["in_hat"] - df["out_hat"]
    df["bal_hat"] = df["bal_asof"] + net.groupby([df["model"], df["company_id"], df["as_of"]]).cumsum()
    df["bal_flow_true"] = df["bal_asof"] + df["dflow_true"]
    df["bal_valid"] = df["y_in"].notna() & ~df["gap_between"]
    return df


def _wape(y: pd.Series, yhat: pd.Series) -> float:
    denom = y.abs().sum()
    return float((y - yhat).abs().sum() / denom) if denom > 0 else np.nan


def _weekly(t: pd.DataFrame) -> pd.DataFrame:
    """Суммы потока по неделям горизонта (h 1–5, 6–10, …); берутся только полные недели без пропусков."""
    wk = t.assign(week=(t["h"] - 1) // WEEK)
    agg = wk.groupby(["company_id", "as_of", "week"])[["y_in", "y_out", "in_hat", "out_hat"]].agg(["sum", "size"])
    full = agg[("y_in", "size")] == WEEK
    return pd.DataFrame({c: agg.loc[full, (c, "sum")] for c in ["y_in", "y_out", "in_hat", "out_hat"]})


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Таблица метрик по группам. df — результат add_balance_paths."""
    def one(g: pd.DataFrame) -> pd.Series:
        t = g[g["target_valid"]]
        w = _weekly(t)
        res = {
            "n_origins": g[["company_id", "as_of"]].drop_duplicates().shape[0],
            "n_companies": g["company_id"].nunique(),
            "wape_in": _wape(t["y_in"], t["in_hat"]),
            "wape_out": _wape(t["y_out"], t["out_hat"]),
            "wape_in_week": _wape(w["y_in"], w["in_hat"]),
            "wape_out_week": _wape(w["y_out"], w["out_hat"]),
        }
        b = g[g["bal_valid"]]
        for h, tag in REPORT_H.items():
            bh = b[b["h"] == h]
            err = bh["bal_hat"] - bh["bal_flow_true"]
            res[f"mae_bal_{tag}"] = err.abs().mean()
            res[f"nmae_bal_{tag}"] = (err.abs() / bh["scale"]).mean()   # в «дневных оборотах»
            res[f"bias_bal_{tag}"] = err.mean()
            res[f"mae_bal_actual_{tag}"] = (bh["bal_hat"] - bh["bal_true"]).abs().mean()
        return pd.Series(res)

    return df.groupby(by, observed=True).apply(one, include_groups=False).reset_index()


def residuals(df: pd.DataFrame) -> pd.DataFrame:
    """Нормированные out-of-sample ошибки по горизонту — вход для Монте-Карло."""
    t = df[df["target_valid"]]
    return pd.DataFrame({
        "model": t["model"], "company_id": t["company_id"], "industry": t["industry"].astype(str),
        "as_of": t["as_of"], "h": t["h"], "target_date": t["target_date"],
        "err_in_norm": (t["y_in"] - t["in_hat"]) / t["scale"],
        "err_out_norm": (t["y_out"] - t["out_hat"]) / t["scale"],
        # накопленная ошибка чистого потока на h — траектория для Монте-Карло
        "err_cum_norm": ((t["bal_flow_true"] - t["bal_hat"]) / t["scale"]).where(t["bal_valid"]),
    }).reset_index(drop=True)
