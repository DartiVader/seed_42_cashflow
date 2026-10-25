"""Backtest с регулярными событиями: модель учит нерегулярную часть потока, регулярная приходит событиями.

Всё по as_of: разметка Влада (ml.pipeline.regular) считается заново на каждом cutoff фолда (для обучения)
и на каждой точке прогноза (признаки и события). Факт — полный поток y, как в обычном backtest,
поэтому ошибки сравнимы со строкой «без событий».

Дорогая часть (разметка × 8 тыс. дат) считается один раз в кэш (build_cache), варианты абляции берут
из него свою группу категорий.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ml.evaluation.backtest import BacktestConfig
from ml.evaluation.splits import holdout_companies, month_cutoffs
from ml.forecast.features import ALL_FEATURES, ID_COLS, attach_targets, make_rows, weekly_origins
from ml.forecast.panel import build_panel, residual_panel
from ml.pipeline import regular as reg
from ml.pipeline.probable import expected_daily, probable_streams
from ml.pipeline.restore import restored_analysis

log = logging.getLogger(__name__)

# варианты абляции: какие категории идут событиями (и вычищаются из цели модели)
VARIANTS: dict[str, frozenset[str]] = {
    "tax": reg.TAX,
    "tax_salary": reg.TAX | reg.SALARY,
    "mandatory": reg.MANDATORY_CATEGORIES,
    "mandatory_revenue": reg.MANDATORY_CATEGORIES | reg.REVENUE,
    # 8.3: + вероятностные события нерегулярных клиентов и поставщиков (ml.pipeline.probable)
    "mandatory_prob": reg.MANDATORY_CATEGORIES | {"prob_revenue_client", "prob_suppliers"},
    # 8.5: те же обязательные, но разметка и события — по восстановленному ряду (ml.pipeline.restore)
    "mandatory_cf": reg.MANDATORY_CATEGORIES,
}
PROB_VARIANTS = {"mandatory_prob"}
RESTORED_VARIANTS = {"mandatory_cf"}
ROW_COLS = ID_COLS + ["scale", "industry", "hist_len"]


@dataclass(frozen=True)
class RegularCache:
    labels: pd.DataFrame   # cutoff, op_index, category — регулярные операции на cutoff фолда
    events: pd.DataFrame   # company_id, as_of, date, amount, category, confidence, mandatory, overdue
    rows: dict[str, pd.DataFrame]   # вариант → строки признаков на точках прогноза

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.labels.to_parquet(path / "labels.parquet", index=False)
        self.events.to_parquet(path / "events.parquet", index=False)
        for v, r in self.rows.items():
            r.to_parquet(path / f"rows_{v}.parquet", index=False)

    @classmethod
    def load(cls, path: Path) -> "RegularCache":
        rows = {v: pd.read_parquet(path / f"rows_{v}.parquet") for v in VARIANTS
                if (path / f"rows_{v}.parquet").exists()}
        for r in rows.values():
            for c in ("industry", "legal_form"):
                r[c] = r[c].astype("category")
        return cls(pd.read_parquet(path / "labels.parquet"), pd.read_parquet(path / "events.parquet"), rows)


def _company_job(args) -> tuple[list, list, dict]:
    cid, ops_c, companies, cutoffs, origins, horizon_days, horizon, variants = args
    with_prob = any(v in PROB_VARIANTS for v in variants)
    restore = any(v in RESTORED_VARIANTS for v in variants)
    assert not restore or set(variants) <= RESTORED_VARIANTS, "восстановленный ряд — отдельным кэшем"
    labels, events, rows = [], [], {v: [] for v in variants}
    for c in cutoffs:
        lab = reg.analyze(ops_c, c).labels      # восстановление разметку не меняет
        r = lab[lab["is_regular"]]
        labels.append(pd.DataFrame({"cutoff": c, "op_index": r.index.to_numpy(), "category": r["category"].to_numpy()}))
        if with_prob:   # 8.3: операции вероятностных потоков — категория prob_<…>, чтобы их можно было вычесть из цели
            _, pmask = probable_streams(ops_c, lab, c)
            pr = lab[pmask]
            labels.append(pd.DataFrame({"cutoff": c, "op_index": pr.index.to_numpy(),
                                        "category": "prob_" + pr["category"].astype(str).to_numpy()}))
    for a in origins:
        ra = _analyze(ops_c, a, horizon_days, restore)
        events.extend((cid, a, e.date, e.amount, e.category, e.confidence, e.mandatory, bool(e.overdue_dates))
                      for e in reg.to_events(ra, horizon_days))
        origin = pd.DataFrame({"company_id": [cid], "as_of": [a]})
        lab = ra.labels
        pmask = None
        if with_prob:
            streams, pmask = probable_streams(ops_c, lab, a)
            events.extend((cid, a, r.date, r.amount, r.category, 1.0, False, False)
                          for r in expected_daily(streams, a, horizon_days).itertuples(index=False))
        for v in variants:
            groups = VARIANTS[v]
            mask = lab["is_regular"] & lab["category"].isin(groups)
            if v in PROB_VARIANTS:
                mask = mask | pmask
            p = residual_panel(build_panel(ops_c, companies, regular=mask))
            rows[v].append(make_rows(p, origin, horizon)[ROW_COLS + [c for c in ALL_FEATURES if c not in ROW_COLS]])
    return labels, events, rows


def _analyze(ops_c: pd.DataFrame, as_of, horizon_days: int, restore: bool) -> reg.RegularAnalysis:
    """Разметка Влада на as_of; restore — события по восстановленному ряду (ml.pipeline.restore): перенесённые
    из-за нехватки денег обязательные платежи на нормальных датах. Разметка та же, поэтому нерегулярная часть
    и остаток остаются фактическими."""
    ra = reg.analyze(ops_c, as_of, horizon_days)
    return restored_analysis(ops_c, as_of, ra, horizon_days) if restore else ra


def build_cache(ops: pd.DataFrame, companies: pd.DataFrame, panel: pd.DataFrame,
                cfg: BacktestConfig = BacktestConfig(), horizon_days: int = 45, workers: int = 4,
                variants: tuple[str, ...] = tuple(VARIANTS)) -> RegularCache:
    """ops — после clean_operations; panel — обычная панель (для точек прогноза)."""
    t0 = time.perf_counter()
    cutoffs = month_cutoffs(cfg.first_cutoff, cfg.last_origin)
    origins = weekly_origins(panel, start=cutoffs[0], end=cfg.last_origin, min_history=cfg.min_history)
    origins = origins[origins["as_of"] > cutoffs[0]]
    by_company = origins.groupby("company_id")["as_of"].apply(list).to_dict()
    jobs = [(cid, g, companies, cutoffs, by_company.get(cid, []), horizon_days, cfg.horizon, variants)
            for cid, g in ops.groupby("company_id", sort=True)]
    labels, events, rows = [], [], {v: [] for v in variants}
    with ProcessPoolExecutor(workers) as ex:
        for i, (lab, ev, rw) in enumerate(ex.map(_company_job, jobs), 1):
            labels += lab
            events += ev
            for v in variants:
                rows[v] += rw[v]
            if i % 25 == 0:
                log.info("кэш регулярных: %d/%d компаний, %.0f с", i, len(jobs), time.perf_counter() - t0)
    ev = pd.DataFrame(events, columns=["company_id", "as_of", "date", "amount", "category", "confidence",
                                       "mandatory", "overdue"])
    ev["date"] = pd.to_datetime(ev["date"])
    cache = RegularCache(pd.concat(labels, ignore_index=True), ev,
                         {v: pd.concat(r, ignore_index=True) for v, r in rows.items()})
    log.info("кэш регулярных готов: точек %d, событий %d, %.0f с", len(origins), len(ev), time.perf_counter() - t0)
    return cache


def add_events(rows: pd.DataFrame, in_hat: np.ndarray, out_hat: np.ndarray, events: pd.DataFrame,
               groups: frozenset[str]) -> tuple[np.ndarray, np.ndarray]:
    """Ожидаемая сумма событий (amount × confidence) в день события; события вне горизонта не нужны."""
    ev = events[events["category"].isin(groups)]
    ev = ev.assign(v=ev["amount"] * ev["confidence"])
    daily = ev.groupby(["company_id", "as_of", "date"])["v"].agg(
        inflow=lambda s: s[s > 0].sum(), outflow=lambda s: -s[s < 0].sum())
    keys = pd.MultiIndex.from_frame(rows[["company_id", "as_of", "target_date"]])
    add = daily.reindex(keys).fillna(0.0)
    return in_hat + add["inflow"].to_numpy(), out_hat + add["outflow"].to_numpy()


def run_variant(variant: str, factory: Callable | None, ops: pd.DataFrame, companies: pd.DataFrame,
                panel: pd.DataFrame, cache: RegularCache, cfg: BacktestConfig = BacktestConfig(),
                name: str | None = None) -> pd.DataFrame:
    """factory=None — нулевая модель нерегулярной части (прогноз = только события)."""
    holdout = holdout_companies(companies, cfg.holdout_per_industry, cfg.seed)
    groups = VARIANTS[variant]
    rows_all = cache.rows[variant]
    cutoffs = month_cutoffs(cfg.first_cutoff, cfg.last_origin)
    bounds = cutoffs[1:] + [pd.Timestamp(cfg.last_origin)]
    parts = []
    for cutoff, upper in zip(cutoffs, bounds):
        rows = rows_all[(rows_all["as_of"] > cutoff) & (rows_all["as_of"] <= upper)].reset_index(drop=True)
        if rows.empty:
            continue
        t0 = time.perf_counter()
        if factory is None:
            in_hat = out_hat = np.zeros(len(rows))
        else:
            lab = cache.labels[(cache.labels["cutoff"] == cutoff) & cache.labels["category"].isin(groups)]
            mask = pd.Series(True, index=lab["op_index"].to_numpy()).reindex(ops.index, fill_value=False)
            train = residual_panel(build_panel(ops, companies, regular=mask))
            model = factory()
            model.fit(train[~train["company_id"].isin(holdout)], cutoff)
            assert pd.Timestamp(model.trained_until) <= cutoff < rows["as_of"].min()
            in_hat, out_hat = model.predict_rows(rows, train)
        in_hat, out_hat = add_events(rows, in_hat, out_hat, cache.events, groups)
        parts.append(rows[ROW_COLS].assign(model=name or variant, cutoff=cutoff, in_hat=in_hat, out_hat=out_hat))
        log.info("вариант %s фолд %s: строк %d, %.1f с", name or variant, cutoff.date(), len(rows),
                 time.perf_counter() - t0)
    out = attach_targets(pd.concat(parts, ignore_index=True), panel)
    out["company_set"] = out["company_id"].isin(holdout).map({True: "new_companies", False: "new_dates"})
    out["period"] = (out["as_of"] >= pd.Timestamp(cfg.report_from)).map({True: "report", False: "tune"})
    out["history"] = pd.cut(out["hist_len"], [0, 59, 125, 10**6], labels=["<60", "60-125", "126+"])
    return out


def _labels_job(args) -> pd.DataFrame:
    ops_c, as_of = args
    return reg.analyze(ops_c, as_of).labels[["category", "is_regular"]]


def labels_at(ops: pd.DataFrame, as_of, workers: int = 4) -> pd.DataFrame:
    """Разметка всех компаний на одну дату (для финальной модели): category, is_regular по индексу ops."""
    jobs = [(g, pd.Timestamp(as_of)) for _, g in ops.groupby("company_id", sort=True)]
    with ProcessPoolExecutor(workers) as ex:
        return pd.concat(list(ex.map(_labels_job, jobs))).reindex(ops.index)


def default_workers() -> int:
    return max(1, min(4, (os.cpu_count() or 2) - 1))
