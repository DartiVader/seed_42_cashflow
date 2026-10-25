"""Контракты ML-сервиса: события, сценарий, результат прогноза (JSON — раздел 5 AGENTS.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Event:
    date: date            # ожидаемая дата
    amount: float         # со знаком: + поступление, − списание
    category: str
    source: str           # history | regular | invoice | contract | tax | manual | bank
    confidence: float     # 0..1 — вероятность, что событие состоится
    counterparty_id: str | None = None   # обезличенный ключ, не ИНН
    mandatory: bool = False              # зарплата, налоги, кредит, аренда
    stream_id: str | None = None         # регулярный поток: событие с тем же stream_id заменяет найденное
    overdue_dates: tuple[date, ...] = ()  # просроченный платёж: даты, когда он должен был пройти (в JSON — overdue_from)


@dataclass
class Scenario:
    delay_counterparty: dict[str, int] = field(default_factory=dict)  # id -> сдвиг в днях
    revenue_multiplier: float = 1.0
    extra_expenses: list[Event] = field(default_factory=list)
    fixed_cost_multiplier: float = 1.0


@dataclass
class DataQuality:
    history_days: int
    short_history: bool
    gaps_in_data: int
    days_since_last_operation: int | None = None   # необязательное: выписка может кончаться раньше as_of
    industry_known: bool | None = None   # необязательное: False — отрасли нет в справочнике, прогноз без неё


@dataclass
class DailyBand:
    date: date
    p10: float
    p50: float
    p90: float


@dataclass
class Gap:
    date: date
    shortfall: float          # максимальная глубина за весь горизонт: «какой лимит овердрафта нужен»
    probability: float
    reasons: list[str]
    actions: list[str]
    # необязательные: P10/P90 и нехватка в окне 5 р.д. от даты разрыва — «сколько найти к этой дате»
    shortfall_low: float | None = None
    shortfall_high: float | None = None
    shortfall_at_gap: float | None = None
    shortfall_at_gap_low: float | None = None
    shortfall_at_gap_high: float | None = None
    # необязательное: советы с пересчётом (ml.forecast.advice) — type, stream_id, category, counterparty_name,
    # amount, date_from, date_to, prob_before/after, shortfall_before/after, gap_date_after
    actions_detail: list[dict] | None = None

    OPTIONAL = ("shortfall_low", "shortfall_high", "shortfall_at_gap", "shortfall_at_gap_low",
                "shortfall_at_gap_high")


# already_negative — остаток на as_of уже ниже порога; gap_expected — разрыв впереди; ok — разрывов нет
STATUSES = ("already_negative", "gap_expected", "ok")


@dataclass
class ForecastResult:
    company_id: str
    as_of: date
    model_version: str
    data_quality: DataQuality
    daily: list[DailyBand]
    events: list[Event]
    gaps: list[Gap]
    status: str = "ok"
    # «Как посчитано»: шаги 1–9 в цифрах, только агрегаты (ml.forecast.trace)
    trace: list[dict] | None = None

    def to_dict(self) -> dict:
        return {
            "company_id": self.company_id,
            "as_of": self.as_of.isoformat(),
            "model_version": self.model_version,
            "data_quality": {"history_days": self.data_quality.history_days,
                             "short_history": self.data_quality.short_history,
                             "gaps_in_data": self.data_quality.gaps_in_data,
                             **({"days_since_last_operation": self.data_quality.days_since_last_operation}
                                if self.data_quality.days_since_last_operation is not None else {}),
                             **({"industry_known": self.data_quality.industry_known}
                                if self.data_quality.industry_known is not None else {})},
            "status": self.status,
            "daily": [{"date": d.date.isoformat(), "p10": round(d.p10), "p50": round(d.p50), "p90": round(d.p90)}
                      for d in self.daily],
            "events": [{"date": e.date.isoformat(), "amount": round(e.amount, 2), "category": e.category,
                        "source": e.source, "confidence": round(e.confidence, 2),
                        **({"stream_id": e.stream_id} if e.stream_id else {}),
                        **({"overdue_from": min(e.overdue_dates).isoformat()} if e.overdue_dates else {})}
                       for e in self.events],
            "gaps": [{"date": g.date.isoformat(), "shortfall": round(g.shortfall),
                      **{k: round(getattr(g, k)) for k in Gap.OPTIONAL if getattr(g, k) is not None},
                      "probability": round(g.probability, 2), "reasons": g.reasons, "actions": g.actions,
                      **({"actions_detail": g.actions_detail} if g.actions_detail is not None else {})}
                     for g in self.gaps],
            **({"trace": self.trace} if self.trace is not None else {}),
        }


class ForecastError(ValueError):
    """Прогноз не строится; текст — понятное предпринимателю сообщение."""


class CompanyClosedError(ForecastError):
    pass


class InvalidStatementError(ForecastError):
    """Выписка из запроса не читается (колонки, типы, даты) — ошибка клиента, HTTP 400."""
