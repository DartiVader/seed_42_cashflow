from __future__ import annotations
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Callable

from .facts import build_facts, facts_hash
from .prompts import build_messages
from .templates import template
from .verify import verify

log = logging.getLogger("explain")
Completer = Callable[[str, list[dict], str], str]


def _strip_names(forecast: dict[str, Any]) -> dict[str, Any]:
    """Названия контрагентов наружу — только при LLM_SEND_NAMES=true; stream_id/ИНН не уходят никогда."""
    keep = os.getenv("LLM_SEND_NAMES", "false").lower() == "true"
    f = dict(forecast)
    f["events"] = [{k: v for k, v in e.items()
                    if k not in ("stream_id", "counterparty_inn", "counterparty_id")
                    and (keep or k not in ("counterparty_name", "label"))}
                   for e in forecast.get("events") or []]
    return f


class Explainer:
    def __init__(self, complete: Completer | None, cache_size: int = 512) -> None:
        self.complete = complete
        self.cache: OrderedDict[str, dict] = OrderedDict()
        self.cache_size = cache_size

    def explain(self, kind: str, forecast: dict, base: dict | None = None, question: str | None = None) -> dict:
        t0 = time.monotonic()
        facts = build_facts(kind, _strip_names(forecast), _strip_names(base) if base else None, question)
        key = facts_hash(facts)
        if key in self.cache:
            return self.cache[key]
        result = {"text": template(facts), "source": "template", "verified": True}
        if self.complete:
            problems: list[str] | None = None
            for _ in range(2):  # попытка + одна повторная с перечнем ошибок
                try:
                    system, messages = build_messages(facts, problems)
                    text = self.complete(system, messages, kind)
                except Exception as exc:  # таймаут/сеть — шаблон
                    log.warning("llm_error kind=%s err=%s", kind, type(exc).__name__)
                    break
                ok, problems = verify(text, facts)
                if ok:
                    result = {"text": text, "source": "llm", "verified": True}
                    break
                log.info("verify_failed kind=%s n=%d", kind, len(problems))
        log.info("explain kind=%s source=%s ms=%d", kind, result["source"], (time.monotonic() - t0) * 1000)
        if result["source"] == "llm" or not self.complete:
            self.cache[key] = result
            if len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return result
