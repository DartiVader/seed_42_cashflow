from __future__ import annotations
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from explain.llm import LLMClient
from explain.service import Explainer

app = FastAPI(title="Seed 42 — объяснения прогноза")
_llm = LLMClient()
explainer = Explainer(_llm.complete if _llm.enabled else None)


class ExplainIn(BaseModel):
    kind: Literal["summary", "gap", "scenario", "answer"]
    forecast: dict[str, Any]
    base: dict[str, Any] | None = None
    question: str | None = Field(default=None, max_length=300)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "llm": _llm.enabled}


@app.post("/explain")
def explain(body: ExplainIn) -> dict:
    return explainer.explain(body.kind, body.forecast, body.base, body.question)
