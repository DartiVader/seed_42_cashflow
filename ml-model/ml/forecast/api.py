"""forecast() — единая точка входа прогноза для ML-сервиса.

Данные (панель, модель, пул ошибок) приходят через ForecastContext: сама функция не ходит
ни в БД, ни в файлы. Оркестратор собирает контекст один раз при старте (ForecastContext.load).

Регулярные платежи. Если версия модели обучена на нерегулярной части потока (events.json в каталоге
версии, event_groups в контексте), forecast() сам находит регулярные события по истории ≤ as_of
(ml.pipeline.regular) и вычитает их из истории для модели. События на вход — любые: событие с тем же
stream_id заменяет найденное по истории с даты события. У версии без events.json (lgbm-v1, lgbm_net-v1)
регулярные платежи сидят в прогнозе модели — им на вход только то, чего нет в истории.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import json

import numpy as np
import pandas as pd

from ml.data.calendar import all_working_days, last_working_day
from ml.evaluation.calibration import Calibrator, ShortfallCalibrator
from ml.forecast.contracts import (CompanyClosedError, DailyBand, DataQuality, Event, ForecastError,
                                   ForecastResult, Scenario)
from ml.forecast.features import funding_window
from ml.forecast.gaps import GapConfig, detect_gap, funding_reason
from ml.forecast.models.base import RowModel
from ml.forecast.advice import Expected, Situation, advise
from ml.forecast.montecarlo import McConfig, bands, draw, error_pool, paths_from, pick_pool
from ml.forecast.statement import company_row, validate_statement
from ml.pipeline.clean import clean_operations
from ml.forecast.panel import build_panel, residual_panel
from ml.forecast.scenario import apply_scenario
from ml.forecast import trace as tr
from ml.pipeline.regular import REVENUE, RegularAnalysis, analyze, merge_events, to_events

SHORT_HISTORY_DAYS = 60
CLOSED_AFTER_DAYS = 30        # нет операций дольше — считаем счёт неактивным
SILENT_TAIL_DAYS = 20         # или столько рабочих дней подряд без операций в конце
DEFAULT_MODEL = "lgbm_net"    # резерв: lgbm (models/lgbm-v1)
DEFAULT_VERSION = "v2"        # lgbm_net-v2: регулярные обязательные платежи событиями; v1 — без событий


@dataclass
class ForecastContext:
    panel: pd.DataFrame
    model: RowModel
    pool: dict[str, np.ndarray]
    model_version: str
    mc: McConfig = field(default_factory=McConfig)
    gap: GapConfig = field(default_factory=GapConfig)
    # вероятность «придётся искать деньги» (контрфактическая метка), см. ml/evaluation/calibration.py
    calibrator: Calibrator | None = None
    shortfall_calibrator: ShortfallCalibrator | None = None
    # регулярные события: операции после clean_operations и группы категорий, которые модель не прогнозирует
    ops: pd.DataFrame | None = None
    companies: pd.DataFrame | None = None
    event_groups: frozenset[str] | None = None
    # просроченные поступления клиентов (категории выручки вне event_groups) — событиями в прогноз, с уверенностью
    # по истории задержек контрагента (ml.pipeline.regular.overdue_receipt_confidence); иначе их ждёт только модель
    carry_overdue_receipts: bool = False

    @classmethod
    def load(cls, data_dir: str | Path, models_dir: str | Path, residuals_path: str | Path,
             model: str = DEFAULT_MODEL, version: str = DEFAULT_VERSION) -> "ForecastContext":
        """models_dir — реестр (models/), версия берётся из models_dir/<model>-<version>.
        Путь прямо на каталог версии (с meta.json) тоже принимается — по-старому."""
        from ml.data.loaders import load_dataset
        from ml.forecast.models import load_model
        from ml.forecast.panel import build_panel
        from ml.pipeline.clean import clean_operations

        model_dir = Path(models_dir)
        if not (model_dir / "meta.json").exists():
            model_dir = model_dir / f"{model}-{version}"
        ops, companies = load_dataset(data_dir)
        ops = clean_operations(ops)
        panel = build_panel(ops, companies)
        m = load_model(model_dir)
        ev_path = model_dir / "events.json"
        ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else None
        # пул ошибок и калибровка — той же модели и того же варианта событий, что прогнозирует
        if ev is not None:
            pool = error_pool(pd.read_parquet(model_dir / "residuals.parquet"), ev["residual_model"],
                              m.config.horizon)
        else:
            pool = error_pool(pd.read_parquet(residuals_path), m.name, m.config.horizon)
        cal_path = model_dir / "calibration.json"
        calibrator = Calibrator.load(cal_path) if cal_path.exists() else None
        sf_path = model_dir / "shortfall_calibration.json"
        sf_cal = ShortfallCalibrator.load(sf_path) if sf_path.exists() else None
        return cls(panel=panel, model=m, pool=pool, model_version=model_dir.name, calibrator=calibrator,
                   shortfall_calibrator=sf_cal, ops=ops, companies=companies,
                   event_groups=frozenset(ev["groups"]) if ev is not None else None)

def forecast(company_id: str, as_of: date, horizon_days: int = 30,
             events: list[Event] | None = None,
             scenario: Scenario | None = None,
             n_paths: int = 1000, seed: int = 42, *,
             context: ForecastContext,
             ops: pd.DataFrame | None = None,
             industry: str | None = None,
             advice: bool = True) -> ForecastResult:
    """ops — выписка из запроса (колонки как в датасете): панель, разметка, scale и история строятся по ней;
    модель, калибровка и пул ошибок — из контекста. industry — отрасль, если компании нет в справочнике.
    advice — советы с пересчётом (ml.forecast.advice) в gaps[].actions / actions_detail."""
    as_of = pd.Timestamp(as_of)
    clock = tr.Clock()
    data = _company_data(company_id, as_of, context, ops, industry)
    hist = data.panel[data.panel["date"] <= as_of]
    if hist.empty:
        raise ForecastError(f"Нет данных по компании {company_id} на {as_of:%d.%m.%Y}")
    last_op = _check_active(hist, as_of)

    anchor = hist["date"].iloc[-1]
    last = hist.iloc[-1]
    end = as_of + pd.Timedelta(days=horizon_days)
    wd = all_working_days()
    days = wd[(wd > anchor) & (wd <= end)]
    if len(days) == 0:
        raise ForecastError("Горизонт прогноза не содержит рабочих дней")
    clock.lap(1)

    # всё дорогое — один раз на запрос: разметка, события, прогноз модели, случайности Монте-Карло
    model_hist, found, extra, names, discretionary, ra = hist, [], [], {}, [], None
    if context.event_groups is not None:
        model_hist, found, extra, names, discretionary, ra = _regular(data, as_of, horizon_days, context)
    clock.lap(3)    # категории и регулярные — один проход кода Влада, время шага 2 входит сюда
    pred = context.model.predict(model_hist, anchor, len(days))
    in_hat, out_hat = pred["in_hat"].to_numpy(), pred["out_hat"].to_numpy()
    model_in, model_out = in_hat, out_hat
    clock.lap(5)
    merged = merge_events(found, events or [])
    clock.lap(4)
    in_hat, out_hat, evs = apply_scenario(in_hat, out_hat, merged, scenario)
    clock.lap(8)
    evs = [e for e in evs if anchor < _to_working(e.date) <= days[-1]]
    pos = np.array([days.searchsorted(_to_working(e.date)) for e in evs], dtype=int)
    extra = [x for x in extra if anchor < x.date <= days[-1]]
    for k, x in enumerate(extra):
        x.row = len(evs) + k
    clock.lap(4)

    short = int(last["hist_len"]) < SHORT_HISTORY_DAYS
    rng = np.random.default_rng(seed)
    industry_key = last.get("industry") if data.industry_known else None
    errors = pick_pool(context.pool, industry_key, context.mc)
    b0 = float(last["balance_eod"])
    draws = draw(errors, len(days), float(last["scale"]), n_paths, len(evs) + len(extra), rng,
                 widen=context.mc.short_history_widen if short else 1.0)
    situation = Situation(days=days, future=np.asarray(days > as_of), as_of=as_of, end=end.date(), b0=b0,
                          in_hat=in_hat, out_hat=out_hat, draws=draws, events=evs, pos=pos, expected=extra,
                          names=names, founder_funded=False, cfg=context.gap, calibrator=context.calibrator,
                          shortfall_cal=context.shortfall_calibrator, discretionary=discretionary)
    paths = paths_from(b0, in_hat - out_hat, draws, situation.base_items())
    clock.lap(6)
    # прогноз идёт от последнего дня с данными, но разрыв ищем только после as_of: прошлое не предсказываем
    future = situation.future
    if not future.any():
        raise ForecastError("Горизонт прогноза не содержит рабочих дней после даты прогноза")
    net_hat = in_hat - out_hat
    lead = _lead_reasons(hist, as_of, context.gap)
    situation.founder_funded = bool(lead)
    gap = detect_gap(days[future], paths[:, future], evs, net_hat[future], b0, context.gap,
                     horizon_end=end.date(), lead_reasons=lead, founder_funded=bool(lead),
                     shortfall_cal=context.shortfall_calibrator)
    if gap and context.calibrator is not None:
        gap = replace(gap, probability=float(context.calibrator(gap.probability)))
    if gap and advice:
        gap = advise(gap, situation)
    clock.lap(7)
    status = "already_negative" if b0 < context.gap.threshold else ("gap_expected" if gap else "ok")
    past = (data.ops["operation_date"] <= as_of) if data.ops is not None else None
    trace = tr.build({
        1: tr.clean_step(data.ops, hist, as_of),
        2: tr.categories_step(ra.labels if ra else None, past),
        3: tr.regular_step(ra.streams if ra else None, ra.labels if ra else None, past, found),
        4: tr.events_step(evs, extra, events),
        5: tr.model_step(context.model_version, getattr(context.model, "name", ""), model_in, model_out,
                         float(last["scale"]), len(days)),
        6: tr.mc_step(paths, future, n_paths, seed, errors is context.pool.get(industry_key), len(errors),
                      context.mc.short_history_widen if short else 1.0),
        7: tr.gap_step(paths, future, context.gap.threshold, context.gap.p_day_min, context.calibrator, gap, status),
        8: tr.scenario_step(scenario),
    }, clock.ms)
    return ForecastResult(
        company_id=company_id,
        as_of=as_of.date(),
        model_version=context.model_version,
        data_quality=DataQuality(history_days=int(last["hist_len"]), short_history=short,
                                 gaps_in_data=_gap_count(hist),
                                 days_since_last_operation=(as_of - last_op).days,
                                 industry_known=None if data.industry_known else False),
        daily=_daily(as_of, horizon_days, anchor, days, bands(paths), b0),
        events=sorted(evs, key=lambda e: e.date),
        gaps=[gap] if gap else [],
        status=status,
        trace=trace,
    )


@dataclass
class CompanyData:
    ops: pd.DataFrame | None      # после clean_operations
    companies: pd.DataFrame       # строка справочника
    panel: pd.DataFrame           # панель компании (вся история)
    industry_known: bool


def _company_data(company_id: str, as_of: pd.Timestamp, context: ForecastContext,
                  ops: pd.DataFrame | None, industry: str | None) -> CompanyData:
    """Данные компании: из выписки запроса (ops) или из контекста. Только ≤ as_of для выписки запроса."""
    known_industries = set(getattr(context.model, "categories", {}).get("industry", []))
    if ops is not None:
        ops_c = clean_operations(validate_statement(ops, company_id, as_of))
        comp, known = company_row(company_id, context.companies, industry)
        known = known and str(comp["industry"].iloc[0]) in known_industries
        return CompanyData(ops_c, comp, build_panel(ops_c, comp), known)
    panel = context.panel[context.panel["company_id"] == company_id]
    ops_c = context.ops[context.ops["company_id"] == company_id] if context.ops is not None else None
    comp = (context.companies[context.companies["company_id"] == company_id]
            if context.companies is not None else None)
    known = panel.empty or str(panel["industry"].iloc[0]) in known_industries or not known_industries
    return CompanyData(ops_c, comp, panel, known)


def _regular(data: CompanyData, as_of: pd.Timestamp, horizon_days: int,
             context: ForecastContext) -> tuple[pd.DataFrame, list[Event], list[Expected], dict[str, str], list,
                                                RegularAnalysis]:
    """История для модели без регулярной части, регулярные события, ожидаемые необязательные платежи потока
    модели и крупнейшие необязательные категории списаний (для советов), имена контрагентов потоков —
    всё по операциям ≤ as_of."""
    ra = analyze(data.ops, as_of.date(), horizon_days)
    mask = ra.labels["is_regular"] & ra.labels["category"].isin(context.event_groups)
    p = residual_panel(build_panel(data.ops, data.companies, regular=mask))
    all_events = to_events(ra, horizon_days)
    carried = [e for e in all_events if context.carry_overdue_receipts and _overdue_receipt(e)]
    found = [e for e in all_events if e.category in context.event_groups] + carried
    names = (dict(zip(ra.streams["stream_id"], ra.streams["counterparty_name"].astype(str)))
             if not ra.streams.empty else {})
    extra = [Expected(row=-1, date=_to_working(e.date), amount=e.amount, category=e.category,
                      stream_id=e.stream_id, confidence=e.confidence)
             for e in all_events if e.category not in context.event_groups and e not in carried]
    return p[p["date"] <= as_of], found, extra, names, _discretionary(data.ops, ra.labels, as_of), ra


def _overdue_receipt(e: Event) -> bool:
    return e.amount > 0 and bool(e.overdue_dates) and e.category in REVENUE


def _discretionary(ops: pd.DataFrame, labels: pd.DataFrame, as_of: pd.Timestamp, days: int = 91) -> list:
    """Необязательные категории списаний за последние ~3 месяца: [(category, доля)], по убыванию."""
    from ml.pipeline.regular import MANDATORY_CATEGORIES, NEVER_REGULAR
    o = ops.join(labels[["category"]].rename(columns={"category": "cat"}))
    o = o[(o["operation_date"] > as_of - pd.Timedelta(days=days)) & (o["operation_date"] <= as_of)
          & (o["direction"] == "Списание") & o["cat"].notna()
          & ~o["cat"].isin(set(MANDATORY_CATEGORIES) | NEVER_REGULAR)]
    by = o.groupby("cat")["amount"].sum().sort_values(ascending=False)
    return [(c, float(v / by.sum())) for c, v in by.items()] if by.sum() > 0 else []


def _check_active(hist: pd.DataFrame, as_of: pd.Timestamp) -> pd.Timestamp:
    """Дата последней операции; если счёт похож на закрытый — CompanyClosedError."""
    last_op = hist.loc[hist["n_ops"] > 0, "date"].max()
    silent_tail = (hist["n_ops"].iloc[-SILENT_TAIL_DAYS:] == 0).all() and len(hist) >= SILENT_TAIL_DAYS
    if (as_of - last_op).days > CLOSED_AFTER_DAYS or silent_tail:
        raise CompanyClosedError(
            f"По счёту нет операций с {last_op:%d.%m.%Y}. Похоже, счёт закрыт или не используется — "
            "прогноз не строим. Загрузите актуальную выписку.")
    return last_op


def _lead_reasons(hist: pd.DataFrame, as_of: pd.Timestamp, cfg: GapConfig) -> list[str]:
    note = funding_reason(funding_window(hist), as_of.date(), cfg)
    return [note] if note else []


def _gap_count(hist: pd.DataFrame) -> int:
    g = hist["gap_in_data"].to_numpy()
    return int(np.sum(g & ~np.r_[False, g[:-1]]))


def _to_working(d: date) -> pd.Timestamp:
    """Платёж в нерабочий день проходит в следующий рабочий."""
    wd = all_working_days()
    return wd[wd.searchsorted(pd.Timestamp(d))]


def _daily(as_of, horizon_days, anchor, days, q: np.ndarray, b0: float) -> list[DailyBand]:
    """По календарным дням: выходной наследует остаток предыдущего рабочего дня."""
    out = []
    for k in range(1, horizon_days + 1):
        d = as_of + pd.Timedelta(days=k)
        i = days.searchsorted(d, side="right") - 1
        p10, p50, p90 = (b0, b0, b0) if i < 0 else q[:, i]
        out.append(DailyBand(date=d.date(), p10=float(p10), p50=float(p50), p90=float(p90)))
    return out
