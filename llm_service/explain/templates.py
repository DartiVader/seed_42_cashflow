"""Шаблонные объяснения: показываются сразу и как запасной вариант, если LLM не прошла проверку."""
from __future__ import annotations
from typing import Any


def template(facts: dict[str, Any]) -> str:
    kind = facts.get("kind")
    if kind == "scenario":
        now, sc = facts.get("now") or {}, facts.get("scenario") or {}
        low = (sc.get("lowest_day") or {})
        text = f"В этом сценарии самый низкий остаток — около {low.get('balance', '—')} ({low.get('date', '—')})."
        if sc.get("gap"):
            text += f" Нехватка денег {sc['gap']['probability_word']} с {sc['gap']['date']}."
        elif now.get("gap"):
            text += " Нехватки денег в этом сценарии не ожидается."
        return text
    gap = facts.get("gap")
    if kind == "gap" and gap:
        text = f"С {gap['date']} {gap['probability_word']} не хватит денег: до {gap.get('shortfall_week', gap['shortfall_month'])}."
        mand = gap.get("mandatory_before_gap") or []
        if mand:
            text += " Главные платежи до этого: " + ", ".join(f"{m['what'].lower()} {m['date']} — {m['amount']}" for m in mand[:2]) + "."
        best = gap.get("best_action")
        if best:
            text += f" Лучший шаг — {best['what']}"
            if best.get("risk_before") and best.get("risk_after"):
                text += f": риск снизится с {best['risk_before']} до {best['risk_after']}"
            text += "."
        return text
    if facts.get("status") == "already_negative":
        return f"Счёт уже в минусе: {facts.get('balance_now', '')}. Сначала закройте обязательные платежи и поговорите с банком о лимите."
    text = ""
    if facts.get("balance_now"):
        text = f"Сейчас на счёте {facts['balance_now']}. "
    if gap:
        text += f"С {gap['date']} {gap['probability_word']} не хватит денег — до {gap.get('shortfall_week', gap['shortfall_month'])}."
    else:
        low = facts.get("lowest_day") or {}
        text += f"Денег хватает весь месяц, самый низкий остаток — около {low.get('balance', '—')} ({low.get('date', '—')})."
    return text.strip()
