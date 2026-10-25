"""Советы при кассовом разрыве с проверкой пересчётом.

Прогноз модели, события и случайности Монте-Карло (траектории ошибок и монетки событий) считаются один раз
на запрос; каждый кандидат меняет только события или out-часть потока модели и пересобирает траектории на тех
же случайностях — эффект совета не тонет в шуме разных выборок, пересчёт детерминирован.

Кандидаты (окно = [as_of+1, дата разрыва + 5 р.д.]):
  postpone            — отложить крупнейшее необязательное списание (не поставщик);
  negotiate_supplier  — перенести крупнейший платёж поставщику на неделю;
  speed_up_receivable — ускорить ожидаемое поступление клиента (после разрыва → за день до него), вероятность × 0,7;
  cut_discretionary   — сократить нерегулярные списания модели в окне на 20 %;
  overdraft           — лимит = P90 нехватки, всегда последним.
Обязательные платежи (налоги, зарплата, кредит, лизинг, аренда, коммунальные, связь, банк, ГПХ) не переносятся.
Совет попадает в ответ, если вероятность снизилась ≥ 0,10 или нехватка к дате — на ≥ 20 %.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from ml.forecast.contracts import Event, Gap
from ml.forecast.gaps import CATEGORY_LABELS, GapConfig, finalize_shortfall, money, overdraft_text, shortfall_stats
from ml.forecast.montecarlo import McDraws, paths_from
from ml.pipeline.regular import MANDATORY_CATEGORIES
from ml.pipeline.vlad.payment_categories import CATEGORIES

SUPPLIERS = {"suppliers", "purchase"}
RECEIVABLE_CATEGORIES = {"revenue_client", "invoice", "contract"}
RECEIVABLE_SOURCES = {"invoice", "contract"}
# названия категорий (по-русски) и их форма для «Сократите на 20% …» (винительный падеж)
CATEGORY_NAMES_RU = {c: v[1] for c, v in CATEGORIES.items()}
CUT_WORDS = {
    "suppliers": "закупки", "services_other": "услуги подрядчиков", "marketing": "рекламу",
    "transport": "перевозки", "software": "подписки", "capex": "покупку оборудования",
    "owner_withdrawal": "вывод денег владельцем",
}
# обязательные — и по категории (если флаг события не выставлен), и по флагу mandatory
NEVER_MOVE = set(MANDATORY_CATEGORIES) | {"salary", "tax", "loan", "rent", "utilities", "leasing"}


@dataclass(frozen=True)
class AdviceConfig:
    window_after_gap: int = 5          # рабочих дней после даты разрыва
    postpone_after_recovery: int = 2   # перенос — на дату, когда P50 снова выше порога, + 2 р.д.
    negotiate_days: int = 7            # перенос платежа поставщику, календарных дней
    receivable_conf_factor: float = 0.7
    cut_share: float = 0.2
    min_prob_drop: float = 0.10
    min_shortfall_drop: float = 0.20
    max_advice: int = 3
    combo_if_prob_above: float = 0.3
    top_per_type: int = 3              # сколько крупнейших платежей пересчитать на каждый тип совета
    combo_min_prob_gain: float = 0.02  # «Вместе» показываем, если лучше каждого совета на столько
    combo_min_shortfall_gain: float = 0.05


@dataclass
class Expected:
    """Ожидаемый платёж, который модель уже учитывает в потоке (регулярный необязательный поток Влада)."""
    row: int                 # строка монетки в McDraws.u
    date: pd.Timestamp
    amount: float            # со знаком
    category: str
    stream_id: str | None
    confidence: float


@dataclass
class Situation:
    """Всё, что нужно пересчёту: посчитано один раз в forecast()."""
    days: pd.DatetimeIndex           # рабочие дни горизонта (с дня после последних данных)
    future: np.ndarray               # маска дней после as_of
    as_of: pd.Timestamp
    end: date                        # конец горизонта (календарный)
    b0: float
    in_hat: np.ndarray
    out_hat: np.ndarray
    draws: McDraws
    events: list[Event]              # строка монетки = индекс события
    pos: np.ndarray
    expected: list[Expected]
    names: dict[str, str]            # stream_id → counterparty_name (в JSON можно, в логи нельзя)
    founder_funded: bool
    cfg: GapConfig
    calibrator: Callable | None = None
    shortfall_cal: object | None = None
    # крупнейшие необязательные категории списаний по истории: (category, доля в необязательных списаниях)
    discretionary: list[tuple[str, float]] = field(default_factory=list)

    def base_items(self) -> list[tuple]:
        return [(i, int(p), e.amount, 0.0, e.confidence) for i, (e, p) in enumerate(zip(self.events, self.pos))]


@dataclass
class Outcome:
    prob: float              # вероятность разрыва за горизонт (калиброванная)
    prob_window: float       # доля траекторий с провалом в окне ±5 р.д. от исходной даты разрыва (без калибровки:
                             # isotonic обучен на вероятности за горизонт, его ступеньки съедают разницу в окне)
    gap_date: date | None    # ближайший разрыв после совета
    total: float             # нехватка за горизонт (медиана макс. глубины среди провалившихся, калиброванная)
    p50: np.ndarray
    depth: float = 0.0       # ожидаемая глубина минуса по всем траекториям (0 у непровалившихся)


@dataclass
class Candidate:
    type: str
    items: Callable[[list], list]               # base items → items совета
    out_hat: Callable[[np.ndarray], np.ndarray]  # out-часть модели → совета
    detail: dict
    text: Callable[[str], str]                  # эффект → строка совета
    short: str                                  # для «Вместе: …»
    outcome: Outcome | None = None


def evaluate(s: Situation, items: list, out_hat: np.ndarray, window: tuple[int, int]) -> Outcome:
    paths = paths_from(s.b0, s.in_hat - out_hat, s.draws, items)[:, s.future]
    below = paths < s.cfg.threshold
    cal = s.calibrator if s.calibrator is not None else (lambda p: p)
    prob = float(cal(float(below.any(axis=1).mean())))
    prob_window = float(below[:, window[0]:window[1] + 1].any(axis=1).mean())
    hit = np.flatnonzero(below.mean(axis=0) >= s.cfg.p_day_min)
    p50 = np.median(paths, axis=0)
    total = 0.0
    if below.any():
        sf = finalize_shortfall(shortfall_stats(paths, int(hit[0]) if len(hit) else 0, s.cfg.threshold,
                                                s.cfg.shortfall_window), s.shortfall_cal)
        total = float(sf["total"][0])
    depth = float(np.maximum(s.cfg.threshold - paths.min(axis=1), 0).mean())
    return Outcome(prob, prob_window, s.days[s.future][int(hit[0])].date() if len(hit) else None, total, p50, depth)


def advise(gap: Gap, s: Situation, cfg: AdviceConfig = AdviceConfig()) -> Gap:
    """Gap с actions (тексты) и actions_detail; овердрафт — всегда последним."""
    fdays = s.days[s.future]
    j = int(fdays.searchsorted(pd.Timestamp(gap.date)))
    window = (max(0, j - cfg.window_after_gap), min(j + cfg.window_after_gap, len(fdays) - 1))
    base_items = s.base_items()
    base = evaluate(s, base_items, s.out_hat, window)
    window_end = fdays[window[1]]
    recovery = _recovery(fdays, base.p50, j, s.cfg.threshold)
    ctx = _Ctx(base, gap.date, window_end.date(), s.end)

    # по каждому типу — до top_per_type крупнейших платежей; в ответ идёт самый действенный (крупнейший платёж
    # бывает после даты разрыва, и его перенос разрыв не трогает)
    cands = [*_postpone(s, gap, window_end, recovery, cfg), *_negotiate(s, window_end, cfg),
             *_speed_up(s, gap, cfg), *_cut(s, window_end, cfg)]
    for c in cands:
        c.outcome = evaluate(s, c.items(base_items), c.out_hat(s.out_hat), window)
    best: dict[str, Candidate] = {}
    for c in cands:
        if c.type not in best or _gain(ctx, c) > _gain(ctx, best[c.type]):
            best[c.type] = c
    good = [c for c in best.values() if _useful(ctx, c, cfg)]
    good.sort(key=lambda c: _gain(ctx, c), reverse=True)
    good = good[:cfg.max_advice]

    details, texts = [], []
    for c in good:
        details.append(_detail(c, base))
        texts.append(c.text(_effect(ctx, c.outcome, shift=c.type in SHIFT_TYPES)))
    combo = None
    if len(good) >= 2 and all(c.outcome.prob > cfg.combo_if_prob_above for c in good):
        a, b = good[0], good[1]
        combo = Candidate("combo", lambda x: x, _same, {}, str, "")
        combo.outcome = evaluate(s, b.items(a.items(base_items)), b.out_hat(a.out_hat(s.out_hat)), window)
        # «Вместе» — только если заметно лучше каждого по отдельности
        if not all(_clearly_better(combo.outcome, c.outcome, cfg) for c in (a, b)):
            combo = None
    if combo is not None:
        details.append({**_outcome_fields(base, combo.outcome), "type": "combo", "parts": [a.type, b.type],
                        "stream_id": None, "category": None, "counterparty_name": None,
                        "amount": None, "date_from": None, "date_to": None})
        texts.append(f"Вместе: {a.short} и {b.short} — {_effect(ctx, combo.outcome, shift=False)}")
    od_detail, od_text = _overdraft(gap, s, j, recovery)
    details.append(od_detail)
    texts.append(od_text)
    return replace(gap, actions=texts, actions_detail=details)


# ---------------------------------------------------------------- кандидаты

def _movable(e_category: str, mandatory: bool) -> bool:
    return not mandatory and e_category not in NEVER_MOVE


def _outflows_in_window(s: Situation, window_end, suppliers: bool, top: int):
    """(ссылка, дата, сумма, категория, stream_id, вероятность): события и ожидаемые платежи потока модели."""
    lo = s.as_of
    out = []
    for i, e in enumerate(s.events):
        d = pd.Timestamp(s.days[s.pos[i]]) if s.pos[i] < len(s.days) else pd.Timestamp(e.date)
        if e.amount < 0 and lo < d <= window_end and _movable(e.category, e.mandatory) \
                and (e.category in SUPPLIERS) == suppliers:
            out.append((("event", i), d, e.amount, e.category, e.stream_id, e.confidence))
    for x in s.expected:
        if x.amount < 0 and lo < x.date <= window_end and _movable(x.category, False) \
                and (x.category in SUPPLIERS) == suppliers:
            out.append((("expected", x.row), x.date, x.amount, x.category, x.stream_id, x.confidence))
    return sorted(out, key=lambda t: t[2])[:top]


def _shift(s: Situation, ref, new_date: pd.Timestamp, amount: float, conf: float, early_conf: float | None = None):
    """Перенос платежа на new_date. Событие — меняем день (early_conf: с этой вероятностью раньше, иначе как было);
    ожидаемый платёж модели — отменяем в старый день и добавляем в новый."""
    kind, idx = ref
    new_pos = int(s.days.searchsorted(new_date))

    def items(base: list) -> list:
        if kind == "event":
            out = [t for t in base if t[0] != idx]
            old = next(t for t in base if t[0] == idx)
            if early_conf is None:
                if new_pos < len(s.days):
                    out.append((idx, new_pos, old[2], old[3], old[4]))
            else:
                out += [(idx, new_pos, old[2], 0.0, early_conf), (idx, old[1], old[2], early_conf, old[4])]
            return out
        old_pos = int(s.days.searchsorted(_date_of(s, ref)))
        p = conf if early_conf is None else early_conf
        out = base + [(idx, old_pos, -amount, 0.0, p)]
        if new_pos < len(s.days):
            out.append((idx, new_pos, amount, 0.0, p))
        return out
    return items


def _date_of(s: Situation, ref) -> pd.Timestamp:
    kind, idx = ref
    if kind == "event":
        return pd.Timestamp(s.days[s.pos[idx]])
    return next(x.date for x in s.expected if x.row == idx)


def _postpone(s: Situation, gap: Gap, window_end, recovery, cfg: AdviceConfig) -> list[Candidate]:
    return [c for f in _outflows_in_window(s, window_end, False, cfg.top_per_type)
            if (c := _postpone_one(s, f, window_end, recovery, cfg)) is not None]


def _postpone_one(s: Situation, found, window_end, recovery, cfg: AdviceConfig) -> Candidate | None:
    ref, d, amount, cat, sid, conf = found
    # на дату, когда P50 снова выше порога + 2 р.д., иначе — на первый рабочий день после окна; не раньше платежа
    target = (_add_wd(s.days, recovery, cfg.postpone_after_recovery) if recovery is not None
              else _add_wd(s.days, window_end, 1))
    target = _within_horizon(s, max(target, _add_wd(s.days, d, 1)), d)
    if target is None:
        return None
    label = _label(cat, sid, s.names)
    detail = _base_detail("postpone", sid, cat, s.names, amount, d, target)
    return Candidate("postpone", _shift(s, ref, target, amount, conf), _same, detail,
                     lambda eff: f"Перенесите платёж {label} {money(amount)} с {d:%d.%m} на {target:%d.%m} — {eff}",
                     f"перенос платежа {label} на {target:%d.%m}")


def _negotiate(s: Situation, window_end, cfg: AdviceConfig) -> list[Candidate]:
    return [c for f in _outflows_in_window(s, window_end, True, cfg.top_per_type)
            if (c := _negotiate_one(s, f, cfg)) is not None]


def _negotiate_one(s: Situation, found, cfg: AdviceConfig) -> Candidate | None:
    ref, d, amount, cat, sid, conf = found
    target = _within_horizon(s, _next_wd(d + pd.Timedelta(days=cfg.negotiate_days)), d)
    if target is None:
        return None
    name = s.names.get(sid) if sid else None
    who = f"поставщиком {name}" if name else "поставщиком"
    detail = _base_detail("negotiate_supplier", sid, cat, s.names, amount, d, target)
    return Candidate("negotiate_supplier", _shift(s, ref, target, amount, conf), _same, detail,
                     lambda eff: f"Договоритесь с {who} о переносе {money(amount)} "
                                 f"с {d:%d.%m} на {target:%d.%m} — {eff}",
                     f"перенос платежа поставщику на {target:%d.%m}")


def _speed_up(s: Situation, gap: Gap, cfg: AdviceConfig) -> list[Candidate]:
    gd = pd.Timestamp(gap.date)
    pool = []
    for i, e in enumerate(s.events):
        d = pd.Timestamp(s.days[s.pos[i]]) if s.pos[i] < len(s.days) else None
        if e.amount > 0 and d is not None and d > gd and (e.category in RECEIVABLE_CATEGORIES
                                                          or e.source in RECEIVABLE_SOURCES):
            pool.append((("event", i), d, e.amount, e.category, e.stream_id, e.confidence))
    for x in s.expected:
        if x.amount > 0 and x.date > gd and x.category in RECEIVABLE_CATEGORIES:
            pool.append((("expected", x.row), x.date, x.amount, x.category, x.stream_id, x.confidence))
    pool = sorted(pool, key=lambda t: -t[2])[:cfg.top_per_type]
    return [_speed_up_one(s, gd, f, cfg) for f in pool]


def _speed_up_one(s: Situation, gd: pd.Timestamp, found, cfg: AdviceConfig) -> Candidate:
    ref, d, amount, cat, sid, conf = found
    fdays = s.days[s.future]
    k = int(fdays.searchsorted(gd))
    target = fdays[max(k - 1, 0)]
    early = conf * cfg.receivable_conf_factor
    name = s.names.get(sid) if sid else None
    who = f"клиента {name}" if name else "клиента"
    detail = _base_detail("speed_up_receivable", sid, cat, s.names, amount, d, target)
    return Candidate("speed_up_receivable", _shift(s, ref, target, amount, conf, early_conf=early), _same, detail,
                     lambda eff: f"Попросите {who} оплатить {money(amount)} до {target:%d.%m} "
                                 f"(ожидается {d:%d.%m}) — {eff}",
                     f"ранняя оплата {who} {money(amount)}")


def _cut(s: Situation, window_end, cfg: AdviceConfig) -> list[Candidate]:
    mask = (s.days > s.as_of) & (s.days <= window_end)
    saved = float(s.out_hat[mask].sum() * cfg.cut_share)
    if saved <= 0:
        return []

    def out_hat(o: np.ndarray) -> np.ndarray:
        o = o.copy()
        o[mask] *= 1 - cfg.cut_share
        return o
    first = s.days[mask][0]
    top = s.discretionary[:3]
    cats = [{"category": c, "name": CATEGORY_NAMES_RU.get(c, c), "amount": round(saved * sh)} for c, sh in top]
    detail = {"type": "cut_discretionary", "stream_id": None, "category": None, "counterparty_name": None,
              "amount": round(saved), "date_from": first.date().isoformat(), "date_to": window_end.date().isoformat(),
              "categories": cats}
    share = round(cfg.cut_share * 100)
    what = _join([CUT_WORDS.get(c, CATEGORY_NAMES_RU.get(c, c).lower()) for c, _ in top]) or "необязательные расходы"
    return [Candidate("cut_discretionary", lambda b: b, out_hat, detail,
                     lambda eff: f"Сократите на {share}% {what} до {window_end:%d.%m} (~{money(saved)}) — {eff}",
                     f"сокращение на {share}% {what}")]


def _overdraft(gap: Gap, s: Situation, j: int, recovery) -> tuple[dict, str]:
    high = gap.shortfall_high if gap.shortfall_high is not None else gap.shortfall
    until = recovery.date() if recovery is not None else None
    text = overdraft_text(gap.shortfall, high, s.end, s.b0, gap.date, until, s.founder_funded)
    detail = {"type": "overdraft", "stream_id": None, "category": None, "counterparty_name": None,
              "amount": round(gap.shortfall), "amount_high": round(high), "date_from": gap.date.isoformat(),
              "date_to": (until or s.end).isoformat(), "prob_before": round(gap.probability, 2), "prob_after": None,
              "shortfall_before": round(gap.shortfall), "shortfall_after": None, "gap_date_after": None}
    return detail, text


# ---------------------------------------------------------------- вспомогательное

def _same(x):
    return x


SHIFT_TYPES = {"postpone", "negotiate_supplier", "speed_up_receivable"}


@dataclass
class _Ctx:
    base: Outcome
    gap_date: date
    window_end: date
    end: date


def _primary(ctx: _Ctx, c: Candidate) -> float:
    """Переносы — по вероятности в окне исходного разрыва, сокращение — по вероятности за горизонт."""
    if c.type in SHIFT_TYPES:
        return ctx.base.prob_window - c.outcome.prob_window
    return ctx.base.prob - c.outcome.prob


def _gain(ctx: _Ctx, c: Candidate) -> tuple[float, float]:
    return round(_primary(ctx, c), 4), ctx.base.total - c.outcome.total


def _clearly_better(o: Outcome, than: Outcome, cfg: AdviceConfig) -> bool:
    return (than.prob - o.prob >= cfg.combo_min_prob_gain
            or (than.total > 0 and (than.total - o.total) / than.total >= cfg.combo_min_shortfall_gain))


def _useful(ctx: _Ctx, c: Candidate, cfg: AdviceConfig) -> bool:
    o, b = c.outcome, ctx.base
    # нехватка за горизонт не уменьшилась и риск не снизился — совет не помогает. Нехватку здесь сравниваем по
    # ожидаемой глубине по всем траекториям: медиана среди провалившихся растёт, когда совет убирает мелкие провалы
    if o.depth >= b.depth and o.prob >= b.prob:
        return False
    sf_drop = (b.total - o.total) / b.total if b.total > 0 else 0.0
    return _primary(ctx, c) >= cfg.min_prob_drop or sf_drop >= cfg.min_shortfall_drop


def _effect(ctx: _Ctx, o: Outcome, shift: bool) -> str:
    b = ctx.base
    if o.gap_date is None:
        risk = (b.prob_window, o.prob_window) if shift else (b.prob, o.prob)
        return f"разрыва до {ctx.end:%d.%m} не будет (риск {risk[0]:.0%} → {risk[1]:.0%})"
    if shift and b.prob_window - o.prob_window >= 0.10:
        if o.gap_date > ctx.window_end:
            return (f"нехватки {ctx.gap_date:%d.%m} не будет (риск {b.prob_window:.0%} → {o.prob_window:.0%}), "
                    f"но ближайший риск сместится на {o.gap_date:%d.%m} (~{o.prob:.0%})")
        return f"риск нехватки {ctx.gap_date:%d.%m} снизится с {b.prob_window:.0%} до {o.prob_window:.0%}"
    if not shift and b.prob - o.prob >= 0.10:
        moved = f", ближайший разрыв — {o.gap_date:%d.%m}" if o.gap_date != ctx.gap_date else ""
        return f"риск нехватки снизится с {b.prob:.0%} до {o.prob:.0%}{moved}"
    return f"нехватка за месяц уменьшится с ~{money(b.total)} до ~{money(o.total)}"


def _outcome_fields(base: Outcome, o: Outcome) -> dict:
    return {"prob_before": round(base.prob, 2), "prob_after": round(o.prob, 2),
            "prob_window_before": round(base.prob_window, 2), "prob_window_after": round(o.prob_window, 2),
            "prob_horizon_after": round(o.prob, 2),
            "shortfall_before": round(base.total), "shortfall_after": round(o.total),
            "gap_date_after": o.gap_date.isoformat() if o.gap_date else None}


def _detail(c: Candidate, base: Outcome) -> dict:
    return {**c.detail, **_outcome_fields(base, c.outcome)}


def _base_detail(kind: str, sid, cat, names, amount, d_from, d_to) -> dict:
    return {"type": kind, "stream_id": sid, "category": cat, "counterparty_name": names.get(sid) if sid else None,
            "amount": round(abs(amount)), "date_from": pd.Timestamp(d_from).date().isoformat(),
            "date_to": pd.Timestamp(d_to).date().isoformat()}


def _within_horizon(s: Situation, target: pd.Timestamp, d: pd.Timestamp) -> pd.Timestamp | None:
    """Перенос за горизонт не проверить пересчётом (платёж просто выпадет) — переносим не дальше конца горизонта."""
    target = min(target, s.days[-1])
    return target if target > d else None


def _join(words: list[str]) -> str:
    return " и ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 1 else "".join(words)


def _label(cat: str, sid: str | None, names: dict) -> str:
    what = CATEGORY_LABELS.get(cat, cat)
    name = names.get(sid) if sid else None
    return f"«{what}»" + (f" ({name})" if name else "")


def _recovery(fdays: pd.DatetimeIndex, p50: np.ndarray, j: int, threshold: float):
    back = np.flatnonzero(p50[j + 1:] >= threshold)
    return fdays[j + 1 + back[0]] if len(back) else None


def _add_wd(days: pd.DatetimeIndex, d, n: int) -> pd.Timestamp:
    from ml.data.calendar import all_working_days
    wd = all_working_days()
    k = int(wd.searchsorted(pd.Timestamp(d))) + n
    return wd[min(k, len(wd) - 1)]


def _next_wd(d) -> pd.Timestamp:
    from ml.data.calendar import all_working_days
    wd = all_working_days()
    return wd[min(int(wd.searchsorted(pd.Timestamp(d))), len(wd) - 1)]
