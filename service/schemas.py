"""Тела запросов. Ошибки валидации отдаются как 400 {"code": "bad_request", ...} (см. main.py)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    date: date
    amount: float
    category: str
    source: str = "manual"
    confidence: float = Field(1.0, ge=0, le=1)
    mandatory: bool = False
    stream_id: str | None = None
    overdue_from: date | None = None      # приходит из ответа /forecast; на расчёт не влияет


class ScenarioIn(BaseModel):
    delay_counterparty: dict[str, int] = {}
    revenue_multiplier: float = Field(1.0, gt=0)
    extra_expenses: list[EventIn] = []
    fixed_cost_multiplier: float = Field(1.0, gt=0)


class ForecastIn(BaseModel):
    as_of: date
    horizon_days: int = Field(30, ge=7, le=90)
    threshold: float = 0
    events: list[EventIn] = []
    scenario: ScenarioIn | None = None
    seed: int = 42


class ProcessIn(BaseModel):
    reason: Literal["upload", "update", "recategorize"] = "upload"
    from_date: date | None = None


class CategoryIn(BaseModel):
    category: str = Field(min_length=1, max_length=64)
