"""Клиент LLM. Ключ только из окружения; без ключа — сразу шаблон."""
from __future__ import annotations
import os


class LLMClient:
    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "anthropic")
        self.timeout = float(os.getenv("LLM_TIMEOUT_S", "4"))
        self.fast = os.getenv("LLM_MODEL_FAST", "claude-haiku-5-5")
        self.smart = os.getenv("LLM_MODEL_SMART", "claude-sonnet-5-5")
        self._client = None
        if self.provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            self._client = anthropic.Anthropic(timeout=self.timeout, max_retries=0)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def complete(self, system: str, messages: list[dict], kind: str) -> str:
        model = self.smart if kind in ("gap", "answer") else self.fast
        resp = self._client.messages.create(model=model, max_tokens=400, temperature=0.2,
                                            system=system, messages=messages)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
