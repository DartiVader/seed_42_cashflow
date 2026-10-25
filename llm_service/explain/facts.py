"""Пакет фактов для LLM: только готовые, отформатированные значения из прогноза.

LLM видит только этот пакет. Все числа уже записаны так, как их можно писать в тексте,
а allowed_numbers / allowed_dates — полный список того, что текст может содержать.
Сырые назначения платежей, ИНН и stream_id сюда не попадают никогда.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]

CATEGORY_NAMES = {
    "salary": "Зарплата", "salary_advance": "Зарплата (аванс)", "salary_settlement": "Зарплата (расчёт)",
    "contractor_gph": "Оплата по договорам ГПХ", "tax_enp": "Единый налоговый платёж",
    "tax_other": "Налоги и взносы", "rent": "Аренда", "utilities": "Коммунальные услуги",
    "telecom": "Связь", "suppliers": "Закупка у поставщика", "capex": "Оборудование и ремонт",
    "software": "Подписки", "marketing": "Реклама", "transport": "Транспорт и топливо",
    "services_other": "Услуги подрядчиков", "loan_repayment": "Погашение кредита", "leasing": "Лизинг",
    "bank_fee": "Комиссии банка", "revenue_client": "Оплата от клиента", "income_subsidy": "Субсидия",
    "other": "Прочий платёж",
}

ADVICE_NAMES = {
    "postpone": "перенести необязательный платёж", "negotiate_supplier": "договориться с поставщиком о переносе",
    "speed_up_receivable": "попросить клиента заплатить раньше", "cut_discretionary": "сократить необязательные расходы",
    "overdraft": "кредитный лимит",
}


def money(value: float) -> str:
    """Тот же формат, что на фронте: «1,2 млн ₽», «458 тыс. ₽», «4,3 тыс. ₽»."""
    sign = "−" if value < 0 else ""
    v = abs(float(value))
    if v >= 1_000_000:
        body = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " млн ₽"
    elif v >= 10_000:
        body = f"{round(v / 1000):d} тыс. ₽"
    elif v >= 1000:
        body = f"{v / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " тыс. ₽"
    else:
        body = f"{round(v):d} ₽"
    return sign + body


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}"


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def pct(p: float) -> str:
    return f"{round(float(p) * 100)}%"


def probability_word(p: float) -> str:
    if p < 0.15:
        return "маловероятно"
    if p < 0.35:
        return "возможно"
    if p < 0.65:
        return "вероятно"
    if p < 0.85:
        return "очень вероятно"
    return "почти наверняка"


def category(code: str | None) -> str:
    return CATEGORY_NAMES.get(code or "", "Платёж")


class FactsBuilder:
    """Собирает факты и параллельно копит разрешённые числа и даты."""

    def __init__(self) -> None:
        self.numbers: set[str] = set()
        self.dates: set[str] = set()

    def m(self, value: float) -> str:
        text = money(value)
        self.numbers.add(text.replace(" ₽", "").lstrip("−"))
        return text

    def d(self, iso: str) -> str:
        self.dates.add(short_date(iso))
        self.dates.add(long_date(iso))
        return short_date(iso)

    def p(self, value: float) -> str:
        text = pct(value)
        self.numbers.add(text)
        return text


def _gap_facts(b: FactsBuilder, forecast: dict[str, Any]) -> dict[str, Any] | None:
    gaps = forecast.get("gaps") or []
    if not gaps:
        return None
    g = gaps[0]
    gap_date = g["date"]
    facts: dict[str, Any] = {
        "date": b.d(gap_date),
        "date_words": long_date(gap_date),
        "probability_word": probability_word(g.get("probability", 0)),
        "probability": b.p(g.get("probability", 0)),
        "shortfall_month": b.m(g.get("shortfall", 0)),
    }
    if g.get("shortfall_at_gap") is not None:
        facts["shortfall_week"] = b.m(g["shortfall_at_gap"])
        if g.get("shortfall_at_gap_low") is not None and g.get("shortfall_at_gap_high") is not None:
            facts["shortfall_week_range"] = [b.m(g["shortfall_at_gap_low"]), b.m(g["shortfall_at_gap_high"])]
    # обязательные платежи около разрыва — из events, а не из текста reasons
    events = forecast.get("events") or []
    near = []
    for e in events:
        if e.get("amount", 0) < 0 and e.get("mandatory") and e["date"] <= gap_date:
            near.append(e)
    near.sort(key=lambda e: e["amount"])
    facts["mandatory_before_gap"] = [
        {"what": category(e.get("category")), "date": b.d(e["date"]), "amount": b.m(-e["amount"]),
         "overdue_from": b.d(e["overdue_from"]) if e.get("overdue_from") else None}
        for e in near[:4]
    ]
    inflows = [e for e in events if e.get("amount", 0) > 0]
    facts["expected_inflows"] = [
        {"what": category(e.get("category")), "date": b.d(e["date"]), "amount": b.m(e["amount"]),
         "certainty": probability_word(e.get("confidence", 1)) if e.get("confidence", 1) < 0.95 else "точно"}
        for e in inflows[:3]
    ]
    details = g.get("actions_detail") or []
    best = next((x for x in details if x.get("type") != "overdraft"), None)
    if best:
        effect = {"what": ADVICE_NAMES.get(best["type"], "совет")}
        if best.get("amount") is not None:
            effect["amount"] = b.m(best["amount"])
        if best.get("date_to"):
            effect["until"] = b.d(best["date_to"])
        before = best.get("prob_window_before", best.get("prob_before"))
        after = best.get("prob_window_after", best.get("prob_after"))
        if before is not None and after is not None:
            effect["risk_before"] = b.p(before)
            effect["risk_after"] = b.p(after)
        facts["best_action"] = effect
    overdraft = next((x for x in details if x.get("type") == "overdraft"), None)
    if overdraft:
        facts["credit_limit"] = b.m(overdraft.get("amount", 0))
    return facts


def _summary_facts(b: FactsBuilder, forecast: dict[str, Any]) -> dict[str, Any]:
    daily = forecast.get("daily") or []
    as_of = forecast["as_of"]
    facts: dict[str, Any] = {
        "as_of": b.d(as_of),
        "status": forecast.get("status"),
        "status_meaning": {
            "ok": "денег хватает весь месяц",
            "gap_expected": "впереди возможна нехватка денег",
            "already_negative": "счёт уже в минусе",
        }.get(forecast.get("status", ""), ""),
    }
    if forecast.get("balance_now") is not None:
        facts["balance_now"] = b.m(forecast["balance_now"])
    if daily:
        lowest = min(daily, key=lambda x: x["p50"])
        facts["lowest_day"] = {"date": b.d(lowest["date"]), "balance": b.m(lowest["p50"])}
        facts["in_30_days"] = b.m(daily[-1]["p50"])
        facts["horizon_end"] = b.d(daily[-1]["date"])
    gap = _gap_facts(b, forecast)
    if gap:
        facts["gap"] = gap
    return facts


def _scenario_facts(b: FactsBuilder, forecast: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "now": _summary_facts(b, base) if base else None,
        "scenario": _summary_facts(b, forecast),
    }


def build_facts(kind: str, forecast: dict[str, Any], base: dict[str, Any] | None = None,
                question: str | None = None) -> dict[str, Any]:
    b = FactsBuilder()
    if kind == "scenario":
        body = _scenario_facts(b, forecast, base)
    elif kind == "gap":
        body = {"as_of": b.d(forecast["as_of"]), "gap": _gap_facts(b, forecast)}
    else:
        body = _summary_facts(b, forecast)
    facts = {"kind": kind, **body}
    if kind == "answer" and question:
        # вопрос пользователя — данные, не инструкции; режем длину и убираем управляющие символы
        facts["question"] = re.sub(r"[\x00-\x1f]", " ", question)[:300]
    facts["allowed_numbers"] = sorted(b.numbers)
    facts["allowed_dates"] = sorted(b.dates)
    return facts


def facts_hash(facts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
