"""Проверка текста LLM до показа: каждое число и дата — из фактов, без запрещённых слов, нужной длины."""
from __future__ import annotations

import re
from typing import Any

from .facts import MONTHS_GEN

FORBIDDEN = [
    "гарантир", "точно будет", "100%", "модель", "p10", "p50", "p90", "коридор", "нейросет",
    "как ии", "искусственн", "квантил", "```", "{\"", "allowed_numbers", "facts",
]

MAX_SENTENCES = {"summary": 3, "gap": 5, "scenario": 3, "answer": 6}
MAX_CHARS = {"summary": 600, "gap": 700, "scenario": 600, "answer": 1000}

_NUM = re.compile(
    r"(?<![\d.])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?\s*(тыс\.?|млн|млрд|%|₽|руб)?",
    re.IGNORECASE,
)
_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.\d{2,4})?\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS_GEN) + r")\b", re.IGNORECASE)


def _norm_number(int_part: str, frac: str | None, unit: str | None) -> str:
    digits = re.sub(r"[   ]", "", int_part)
    value = digits + ("," + frac if frac else "")
    unit = (unit or "").lower()
    if unit.startswith("тыс"):
        return f"{value} тыс."
    if unit in ("млн", "млрд"):
        return f"{value} {unit}"
    if unit == "%":
        return f"{value}%"
    return value


def _allowed_numbers(facts: dict[str, Any]) -> set[str]:
    allowed = set()
    for n in facts.get("allowed_numbers", []):
        m = _NUM.match(n.replace("~", "").strip())
        allowed.add(_norm_number(m.group(1), m.group(2), m.group(3)) if m else n)
    # «в 6 случаях из 10», «на 20%» в формулировке совета, «3 недели» — мелкие целые разрешены
    allowed.update(str(i) for i in range(0, 11))
    return allowed


def sentences(text: str) -> int:
    parts = [p for p in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])", text.strip()) if p.strip()]
    return len(parts)


def verify(text: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    kind = facts.get("kind", "summary")
    low = text.lower()

    for word in FORBIDDEN:
        if word in low:
            problems.append(f"запрещённое слово: «{word}»")

    allowed_dates = set(facts.get("allowed_dates", []))
    allowed_short = {d for d in allowed_dates if re.fullmatch(r"\d{2}\.\d{2}", d)}
    stripped = text
    for m in _DMY.finditer(text):
        dd, mm = int(m.group(1)), int(m.group(2))
        if f"{dd:02d}.{mm:02d}" not in allowed_short:
            problems.append(f"дата не из фактов: {m.group(0)}")
    stripped = _DMY.sub(" ", stripped)
    for m in _DAY_MONTH.finditer(text):
        phrase = f"{int(m.group(1))} {m.group(2).lower()}"
        if phrase not in allowed_dates:
            problems.append(f"дата не из фактов: {m.group(0)}")
    stripped = _DAY_MONTH.sub(" ", stripped)

    allowed = _allowed_numbers(facts)
    for m in _NUM.finditer(stripped):
        token = _norm_number(m.group(1), m.group(2), m.group(3))
        if token not in allowed:
            problems.append(f"число не из фактов: {m.group(0).strip()}")

    if sentences(text) > MAX_SENTENCES.get(kind, 4):
        problems.append(f"слишком много предложений: {sentences(text)}")
    if len(text) > MAX_CHARS.get(kind, 700):
        problems.append(f"слишком длинно: {len(text)} символов")
    if not text.strip():
        problems.append("пустой текст")
    return (not problems, problems)
