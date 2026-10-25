"""Монте-Карло остатка: траектории ошибок из backtest целиком + случайные события.

Ошибка берётся как накопленная ошибка чистого потока err_cum_norm[h] = (факт − прогноз)/scale
одной пары (компания, as_of) по всем h сразу — корреляция между днями сохраняется сама.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ALL = "__all__"


@dataclass(frozen=True)
class McConfig:
    min_pool: int = 30                 # меньше траекторий в отрасли — берём все отрасли
    short_history_widen: float = 1.5   # короткая история — шире коридор


def error_pool(residuals: pd.DataFrame, model: str, horizon: int) -> dict[str, np.ndarray]:
    """Матрицы траекторий ошибок (n × horizon) по отраслям и общая (ключ ALL). Только полные траектории."""
    r = residuals[(residuals["model"] == model) & (residuals["h"] <= horizon)]
    wide = r.pivot_table(index=["industry", "company_id", "as_of"], columns="h", values="err_cum_norm")
    wide = wide.reindex(columns=range(1, horizon + 1)).dropna()
    pool = {ind: g.to_numpy() for ind, g in wide.groupby(level="industry")}
    pool[ALL] = wide.to_numpy()
    return pool


def pick_pool(pool: dict[str, np.ndarray], industry: str | None, cfg: McConfig) -> np.ndarray:
    m = pool.get(industry) if industry is not None else None
    return m if m is not None and len(m) >= cfg.min_pool else pool[ALL]


def extend_errors(errors: np.ndarray, horizon: int) -> np.ndarray:
    """Если горизонт длиннее backtest, ошибка растёт как случайное блуждание: ∝ √h."""
    n = errors.shape[1]
    if horizon <= n:
        return errors[:, :horizon]
    growth = np.sqrt(np.arange(n + 1, horizon + 1) / n)
    return np.hstack([errors, errors[:, [-1]] * growth])


@dataclass
class McDraws:
    """Случайности одного запроса: траектории ошибок (₽) и монетки событий. Советы пересчитываются на них же."""
    err: np.ndarray    # n_paths × H
    u: np.ndarray      # n_items × n_paths, равномерные [0, 1)


def draw(errors: np.ndarray, horizon: int, scale: float, n_paths: int, n_items: int,
         rng: np.random.Generator, widen: float = 1.0) -> McDraws:
    err = extend_errors(errors, horizon)[rng.integers(len(errors), size=n_paths)] * scale * widen
    return McDraws(err, rng.random((n_items, n_paths)))


def paths_from(b0: float, net_hat: np.ndarray, draws: McDraws,
               items: list[tuple[int, int, float, float, float]]) -> np.ndarray:
    """Матрица остатков. items: (строка монетки, день, сумма со знаком, lo, hi) — сумма прибавляется с этого
    дня в траекториях, где lo ≤ u < hi (событие с вероятностью p: lo=0, hi=p)."""
    paths = b0 + np.cumsum(net_hat)[None, :] + draws.err
    for row, pos, amount, lo, hi in items:
        u = draws.u[row]
        paths[:, pos:] += amount * ((u >= lo) & (u < hi))[:, None]
    return paths


def simulate_balance(b0: float, net_hat: np.ndarray, scale: float, errors: np.ndarray,
                     event_pos: np.ndarray, event_amount: np.ndarray, event_conf: np.ndarray,
                     n_paths: int, rng: np.random.Generator, widen: float = 1.0) -> np.ndarray:
    """Матрица остатков n_paths × H.

    net_hat — прогноз чистого потока по рабочим дням (₽); errors — пул траекторий (n × H);
    события: позиция дня, сумма со знаком, вероятность.
    """
    draws = draw(errors, len(net_hat), scale, n_paths, len(event_pos), rng, widen)
    items = [(i, int(p), float(a), 0.0, float(c)) for i, (p, a, c) in enumerate(zip(event_pos, event_amount, event_conf))]
    return paths_from(b0, net_hat, draws, items)


def bands(paths: np.ndarray) -> np.ndarray:
    """P10/P50/P90 по дням: 3 × H."""
    return np.percentile(paths, [10, 50, 90], axis=0)
