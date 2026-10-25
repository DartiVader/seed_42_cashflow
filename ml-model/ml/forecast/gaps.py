"""Детектор кассового разрыва по траекториям Монте-Карло: дата, сумма, вероятность, причины, советы."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ml.forecast.contracts import Event, Gap

CATEGORY_LABELS = {
    "salary": "Зарплата", "tax": "Налоги (ЕНП)", "rent": "Аренда", "loan": "Платёж по кредиту",
    "leasing": "Лизинг", "purchase": "Оплата поставщику", "utilities": "Коммунальные платежи",
    "revenue": "Поступление от клиента", "invoice": "Оплата по счёту",
}
# категории Влада (ml/pipeline/vlad/payment_categories.py) — короткие названия для текстов
CATEGORY_LABELS.update({
    "salary_advance": "Зарплата", "salary_settlement": "Зарплата", "contractor_gph": "Оплата по договорам ГПХ",
    "tax_enp": "ЕНП", "tax_other": "Налоги и взносы", "loan_repayment": "Платёж по кредиту",
    "telecom": "Связь", "bank_fee": "Комиссия банка", "suppliers": "Оплата поставщику",
    "services_other": "Оплата услуг", "software": "Подписки и ПО", "marketing": "Реклама",
    "transport": "Транспорт и топливо", "capex": "Оборудование и ремонт",
})
# просроченный платёж: (сказуемое, причастие) в роде и числе названия
OVERDUE_WORDS = {
    "Зарплата": ("ещё не выплачена", "учтена"), "ЕНП": ("ещё не уплачен", "учтён"),
    "Налоги и взносы": ("ещё не уплачены", "учтены"), "Аренда": ("ещё не оплачена", "учтена"),
    "Лизинг": ("ещё не оплачен", "учтён"), "Коммунальные платежи": ("ещё не оплачены", "учтены"),
    "Связь": ("ещё не оплачена", "учтена"), "Комиссия банка": ("ещё не списана", "учтена"),
    "Оплата по договорам ГПХ": ("ещё не прошла", "учтена"),
}


@dataclass(frozen=True)
class GapConfig:
    threshold: float = 0.0        # 0 или подушка, заданная пользователем
    p_day_min: float = 0.35       # разрыв = первый день с долей провалов ≥ p_day_min; 0,35 — по F1 на tune (9.3, было 0,3)
    reason_window: int = 5        # рабочих дней до даты разрыва, где ищем причины
    shortfall_window: int = 5     # рабочих дней от даты разрыва для shortfall_at_gap
    founder_share_min: float = 0.3  # деньги учредителя / расходы за 60 р.д., выше — «живёт на деньги учредителя»
    no_revenue_ratio: float = 0.05  # выручка за 60 р.д. меньше этой доли расходов — «выручки почти нет»


def detect_gap(dates: pd.DatetimeIndex, paths: np.ndarray, events: list[Event], net_hat: np.ndarray,
               b0: float, cfg: GapConfig = GapConfig(), horizon_end: date | None = None,
               lead_reasons: list[str] | None = None, founder_funded: bool = False,
               shortfall_cal=None) -> Gap | None:
    """lead_reasons — причины из истории компании (funding_reason), идут первыми после «уже в овердрафте».
    shortfall_cal — ml.evaluation.calibration.ShortfallCalibrator (до формирования текстов)."""
    below = paths < cfg.threshold
    p_day = below.mean(axis=0)
    hit = np.flatnonzero(p_day >= cfg.p_day_min)
    if len(hit) == 0:
        return None
    j = int(hit[0])
    failed = below.any(axis=1)
    sf = finalize_shortfall(shortfall_stats(paths, j, cfg.threshold, cfg.shortfall_window), shortfall_cal)
    sf = {k: tuple(float(x) for x in v) for k, v in sf.items()}
    # срок овердрафта: до первого дня после разрыва, когда P50 снова выше порога
    p50 = np.median(paths, axis=0)
    back = np.flatnonzero(p50[j + 1:] >= cfg.threshold)
    until = dates[j + 1 + back[0]].date() if len(back) else None
    end = horizon_end or dates[-1].date()
    return Gap(
        date=dates[j].date(),
        # пользователю — P10/P90; P25/P75 только для метрик backtest
        shortfall=sf["total"][0], shortfall_low=sf["total"][1], shortfall_high=sf["total"][2],
        shortfall_at_gap=sf["at_gap"][0], shortfall_at_gap_low=sf["at_gap"][1], shortfall_at_gap_high=sf["at_gap"][2],
        probability=float(failed.mean()),
        reasons=_reasons(dates, j, events, net_hat, b0, p50, until, end, cfg, lead_reasons or [], sf["at_gap"]),
        # советы с пересчётом — ml.forecast.advice; здесь только овердрафт (лимит — P90 нехватки)
        actions=[overdraft_text(sf["total"][0], sf["total"][2], end, b0, dates[j].date(), until, founder_funded)],
    )


def finalize_shortfall(sf: dict, cal=None) -> dict:
    """Калибровка (если есть) и at_gap ≤ total. Значения — числа или массивы (backtest)."""
    if cal is not None:
        sf = {k: cal.apply(k, *v) for k, v in sf.items()}
    # у каждой траектории «к дате» ≤ «за месяц», но медианы берутся по разным подмножествам
    # (провал в окне / провал где угодно), а калибровки у сумм свои — поэтому ограничиваем явно
    return {**sf, "at_gap": tuple(np.minimum(a, t) for a, t in zip(sf["at_gap"], sf["total"]))}


SF_QUANTILES = (50, 10, 90, 25, 75)   # порядок в кортеже: медиана, P10, P90, P25, P75


def shortfall_stats(paths: np.ndarray, j: int, threshold: float, window: int) -> dict[str, tuple[float, ...]]:
    """Нехватка (медиана, P10, P90, P25, P75) по траекториям, ушедшим ниже порога:
    at_gap — минимум в окне [j, j+window) от даты разрыва, total — минимум за весь горизонт."""
    out = {}
    for kind, part in (("at_gap", paths[:, j:j + window]), ("total", paths)):
        depth = threshold - part.min(axis=1)
        depth = depth[depth > 0]
        q = np.percentile(depth, SF_QUANTILES) if len(depth) else np.zeros(len(SF_QUANTILES))
        out[kind] = tuple(float(v) for v in q)
    return out


def money(x: float) -> str:
    x = abs(x)
    if x >= 1e6:
        return f"{x / 1e6:.1f} млн ₽".replace(".", ",")
    if x >= 1e3:
        return f"{x / 1e3:.0f} тыс. ₽"
    return f"{x:.0f} ₽"


def _label(e: Event) -> str:
    return CATEGORY_LABELS.get(e.category, e.category)


def _in_window(dates, e: Event, lo: int, hi: int) -> bool:
    pos = dates.searchsorted(pd.Timestamp(e.date))
    return lo <= pos <= hi


def funding_reason(stats: dict, as_of: date, cfg: GapConfig = GapConfig()) -> str | None:
    """«Живёт на деньги учредителя»: stats — ml.forecast.features.funding_window по истории до as_of."""
    share = stats["founder_share"]
    if not (share > cfg.founder_share_min and stats["y_in"] <= cfg.no_revenue_ratio * stats["y_out"]):
        return None
    if stats["y_in"] == 0:
        lead, start = "Выручки нет", stats["last_revenue"] or stats["first_date"]
    else:
        lead, start = "Выручки почти нет", stats["window_start"]
    months = max(1, round((pd.Timestamp(as_of) - pd.Timestamp(start)).days / 30.4))
    return (f"{lead} {months} мес., расходы последние месяцы покрывались деньгами учредителя "
            f"(~{money(stats['founder_per_month'])}/мес.)")


def _reasons(dates, j, events, net_hat, b0, p50, until, end, cfg, lead, at_gap) -> list[str]:
    """Заголовок «К дате не хватит ~X» + до трёх причин."""
    lo = max(0, j - cfg.reason_window + 1)
    # просроченные обязательные платежи, перенесённые на дни до разрыва
    overdue = [e for e in events if e.amount < 0 and e.mandatory and e.overdue_dates
               and pd.Timestamp(e.date) <= dates[j]]
    outs = [e for e in events if e.amount < 0 and e.mandatory and not e.overdue_dates
            and _in_window(dates, e, lo, j)]
    outs = sorted(outs, key=lambda e: e.amount)[:3]
    reasons = [*map(_overdue_text, sorted(overdue, key=lambda e: e.amount)),
               *(f"{_label(e)} {e.date:%d.%m} — ~{money(e.amount)}" for e in outs)]
    m, low, high = at_gap[:3]
    last = dates[min(j + cfg.shortfall_window, len(dates)) - 1]
    headline = f"С {dates[j]:%d.%m} по {last:%d.%m} не хватит ~{money(m)}"
    if money(low) != money(high):
        headline += f" (от {money(low)} до {money(high)})"
    if b0 < cfg.threshold:
        # уже ниже порога: говорим о том, что будет дальше, а не о дне разрыва
        first = (f"Счёт уже в овердрафте: −{money(b0)}" if b0 < 0
                 else f"Остаток уже ниже заданной подушки: {money(b0)}")
        return [first, headline, *[*lead, _outlook(b0, p50, until, end, cfg), *reasons][:2]]
    reasons = [*lead, *reasons][:4]
    drift = float(np.sum(net_hat[:j + 1]))
    if drift < 0 and len(reasons) < 3:
        reasons.append(f"До {dates[j]:%d.%m} списания обычно больше поступлений примерно на {money(drift)}")
    return [headline, *(reasons or ["Остаток близок к нулю, обычные колебания платежей могут увести его в минус"])]


def _overdue_text(e: Event) -> str:
    """«Зарплата за 05.10 (~80 тыс. ₽) ещё не выплачена — учтена в прогнозе на 07.10»."""
    label = _label(e)
    verb, part = OVERDUE_WORDS.get(label, ("ещё не прошёл", "учтён"))
    due = " и ".join(f"{d:%d.%m}" for d in e.overdue_dates)
    return f"{label} за {due} (~{money(e.amount)}) {verb} — {part} в прогнозе на {e.date:%d.%m}"


def _outlook(b0, p50, until, end, cfg) -> str:
    change = float(p50[-1] - b0)
    if until is not None:
        return f"Поступления постепенно закрывают минус: выход выше нуля ожидается примерно к {until:%d.%m}"
    if change < 0:
        return f"В ближайший месяц списания обычно больше поступлений примерно на {money(change)}: минус будет расти"
    return f"Поступления постепенно сокращают минус, но выйти в ноль до {end:%d.%m} не успеете"


def overdraft_text(limit: float, high: float, end: date, b0: float, gap_date: date, until: date | None,
                   founder_funded: bool = False) -> str:
    """Совет про овердрафт: лимит — медиана нехватки за горизонт, с запасом — P90; срок — до возврата P50."""
    text = f"Чтобы не уйти в минус до {end:%d.%m}, нужен лимит ~{money(limit)}"
    if money(high) != money(limit):
        text += f", с запасом ~{money(high)}"
    if founder_funded:
        text += " (без новых взносов учредителя)"
    # уже в минусе: объясняем, почему сумма больше текущего минуса
    if b0 < 0 and money(limit) != money(b0) and limit > -b0:
        text += f"; минус может углубиться с {money(b0)} до {money(limit)}"
    if until is not None:
        text += f"; овердрафт понадобится примерно на {(until - gap_date).days} дн. (до {until:%d.%m})"
    return text
