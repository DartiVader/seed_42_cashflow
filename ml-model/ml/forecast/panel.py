"""Дневная панель «компания × рабочий день»: потоки, остаток, пропуски, разовые операции, масштаб.

Все производные величины на дне t считаются только по дням ≤ t (масштаб, порог разовых),
поэтому срез панели по as_of не зависит от будущего.
Исключение — флаг gap_in_data: пропуск виден только по дню, где остаток «скакнул»,
и помечается задним числом. Это маска для обучения и оценки, в признаки он не идёт.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.data.calendar import to_last_working_days, working_days
from ml.data.loaders import INFLOW


@dataclass(frozen=True)
class PanelConfig:
    balance_tol: float = 1.0       # ₽; копейки округления — не пропуск
    oneoff_k: float = 20.0         # разовая операция > k × средний дневной оборот за прошлые 60 дней
    scale_window: int = 60         # рабочих дней
    scale_min_periods: int = 10
    min_scale: float = 1000.0      # ₽; защита от деления на ~0 у «тихих» компаний


PANEL_COLUMNS = [
    "company_id", "date", "n_ops",
    "all_in", "all_out",          # все операции без дублей — для сверки остатка
    "own_in", "own_out",          # переводы собственных средств
    "founder_in", "founder_out",  # займ учредителя и его возврат
    "loan_in",                    # выдача банковского кредита (внутри потока in_flow)
    "rescue_in", "cum_rescue",    # «спасающие» поступления: own_in + founder_in (для контрфактической метки)
    "in_flow", "out_flow",        # поток без own_transfer и ошибочных платежей/возвратов
    "oneoff_in", "oneoff_out",    # разовые крупные операции внутри потока
    "y_in", "y_out",              # поток без разовых (факт для оценки)
    "reg_in", "reg_out",          # регулярная часть y (ml.pipeline.regular); цель модели — y − reg
    "balance_eod", "gap_in_data", "gap_jump", "gap_cum",
    "scale", "hist_len", "cum_y",
]


def build_panel(ops: pd.DataFrame, companies: pd.DataFrame,
                config: PanelConfig = PanelConfig(), regular: pd.Series | None = None) -> pd.DataFrame:
    """ops — результат clean_operations. Возвращает панель, отсортированную по (company_id, date).
    regular — флаг регулярной операции (индекс как у ops; разметка на as_of, ml.pipeline.regular)."""
    ops = ops[~ops["is_duplicate"]]
    ops = ops.assign(is_regular=False if regular is None else regular.reindex(ops.index, fill_value=False))
    parts = [_company_panel(g, config) for _, g in ops.groupby("company_id", sort=True)]
    panel = pd.concat(parts, ignore_index=True)
    meta = companies[["company_id", "industry", "legal_form"]]
    return panel.merge(meta, on="company_id", how="left")


def _company_panel(ops_c: pd.DataFrame, cfg: PanelConfig) -> pd.DataFrame:
    ops_c = ops_c.copy()
    # операции в нерабочий день (в данных их нет) относим к последнему рабочему дню
    ops_c["day"] = to_last_working_days(ops_c["operation_date"])
    dates = working_days(ops_c["day"].min(), ops_c["day"].max())

    inflow = ops_c["direction"] == INFLOW
    own = ops_c["is_own_transfer"]
    founder = ops_c["is_founder_financing"]
    flow = ~own & ~founder & ~ops_c["is_error_refund"]
    oneoff = _oneoff_ops(ops_c, flow, dates, cfg)

    def daily(mask: pd.Series) -> pd.Series:
        return ops_c.loc[mask].groupby("day")["amount"].sum().reindex(dates, fill_value=0.0)

    p = pd.DataFrame({
        "date": dates,
        "n_ops": ops_c.groupby("day").size().reindex(dates, fill_value=0).to_numpy(),
        "all_in": daily(inflow).to_numpy(),
        "all_out": daily(~inflow).to_numpy(),
        "own_in": daily(own & inflow).to_numpy(),
        "own_out": daily(own & ~inflow).to_numpy(),
        "founder_in": daily(founder & inflow).to_numpy(),
        "founder_out": daily(founder & ~inflow).to_numpy(),
        "loan_in": daily(ops_c["is_bank_loan"] & inflow).to_numpy(),
        "in_flow": daily(flow & inflow).to_numpy(),
        "out_flow": daily(flow & ~inflow).to_numpy(),
        "oneoff_in": daily(oneoff & inflow).to_numpy(),
        "oneoff_out": daily(oneoff & ~inflow).to_numpy(),
        # регулярная часть y: разовые уже вычтены из y, поэтому и здесь без них
        "reg_in": daily(flow & ~oneoff & ops_c["is_regular"].astype(bool) & inflow).to_numpy(),
        "reg_out": daily(flow & ~oneoff & ops_c["is_regular"].astype(bool) & ~inflow).to_numpy(),
    })
    p.insert(0, "company_id", ops_c["company_id"].iloc[0])
    p["y_in"] = p["in_flow"] - p["oneoff_in"]
    p["y_out"] = p["out_flow"] - p["oneoff_out"]
    p["rescue_in"] = p["own_in"] + p["founder_in"]
    p["cum_rescue"] = p["rescue_in"].cumsum()

    bal = ops_c.groupby("day")["balance_eod"].first().reindex(dates)
    p["balance_eod"] = bal.ffill().to_numpy()
    p["gap_in_data"], p["gap_jump"] = _detect_gaps(p, bal.to_numpy(), cfg.balance_tol)
    p["gap_cum"] = p["gap_in_data"].cumsum()

    total = (p["y_in"] + p["y_out"]).where(~p["gap_in_data"])
    scale = total.rolling(cfg.scale_window, min_periods=cfg.scale_min_periods).mean()
    scale = scale.fillna(total.expanding(min_periods=1).mean()).ffill()
    p["scale"] = scale.fillna(cfg.min_scale).clip(lower=cfg.min_scale)
    p["hist_len"] = np.arange(1, len(p) + 1)
    p["cum_y"] = (p["y_in"] - p["y_out"]).cumsum()
    return p


def residual_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Панель для модели нерегулярной части: y := y − reg, cum_y пересчитан. scale и остаток — как были."""
    p = panel.assign(y_in=panel["y_in"] - panel["reg_in"], y_out=panel["y_out"] - panel["reg_out"])
    p["cum_y"] = (p["y_in"] - p["y_out"]).groupby(p["company_id"]).cumsum()
    return p


def _detect_gaps(p: pd.DataFrame, bal: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """Пропуск: на дне с операциями остаток не сходится с предыдущим днём с операциями.
    Помечаются дни после предыдущего дня с операциями по текущий включительно."""
    op_pos = np.flatnonzero(p["n_ops"].to_numpy() > 0)
    net = (p["all_in"] - p["all_out"]).to_numpy()
    gap = np.zeros(len(p), dtype=bool)
    jump = np.zeros(len(p))
    for prev, cur in zip(op_pos[:-1], op_pos[1:]):
        diff = bal[cur] - (bal[prev] + net[cur])
        if abs(diff) > tol:
            gap[prev + 1:cur + 1] = True
            jump[cur] = diff
    return gap, jump


def _oneoff_ops(ops_c: pd.DataFrame, flow: pd.Series, dates: pd.DatetimeIndex,
                cfg: PanelConfig) -> pd.Series:
    """Разовая операция: сумма > k × средний дневной оборот потока за прошлые дни (без дня t).
    Два прохода, чтобы прошлая разовая операция не завышала порог для следующей."""
    flow_ops = ops_c.loc[flow]
    turnover = flow_ops.groupby("day")["amount"].sum().reindex(dates, fill_value=0.0)
    flag = pd.Series(False, index=ops_c.index)
    base = turnover
    for _ in range(2):
        thr = cfg.oneoff_k * base.rolling(cfg.scale_window, min_periods=cfg.scale_min_periods).mean().shift(1)
        op_thr = thr.reindex(flow_ops["day"]).to_numpy()
        hit = flow_ops["amount"].to_numpy() > np.nan_to_num(op_thr, nan=np.inf)
        flag[:] = False
        flag.loc[flow_ops.index[hit]] = True
        base = turnover - flow_ops.loc[hit].groupby("day")["amount"].sum().reindex(dates, fill_value=0.0)
    return flag


def data_quality(panel: pd.DataFrame, short_history_days: int = 60) -> pd.DataFrame:
    """Сводка для блока data_quality в ответе сервиса (по каждой компании)."""
    g = panel.groupby("company_id")
    gaps = g["gap_in_data"].apply(lambda s: int((s & ~s.shift(fill_value=False)).sum()))
    out = pd.DataFrame({
        "history_days": g.size(),
        "gaps_in_data": gaps,
        "oneoff_ops_days": g.apply(lambda d: int(((d.oneoff_in + d.oneoff_out) > 0).sum()), include_groups=False),
        "first_date": g["date"].min(),
        "last_date": g["date"].max(),
    })
    out["short_history"] = out["history_days"] < short_history_days
    return out.reset_index()
