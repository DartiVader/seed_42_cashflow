"""Сценарии «что если»: применяются к базовому прогнозу потока и списку событий."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np

from ml.forecast.contracts import Event, Scenario

FIXED_COST_CATEGORIES = {"rent", "purchase", "utilities", "leasing", "suppliers", "telecom"}


def apply_scenario(in_hat: np.ndarray, out_hat: np.ndarray, events: list[Event],
                   scenario: Scenario | None) -> tuple[np.ndarray, np.ndarray, list[Event]]:
    if scenario is None:
        return in_hat, out_hat, list(events)
    in_hat = in_hat * scenario.revenue_multiplier
    out_hat = out_hat * scenario.fixed_cost_multiplier
    out: list[Event] = []
    for e in events:
        amount = e.amount
        if amount > 0:
            amount *= scenario.revenue_multiplier
        elif e.category in FIXED_COST_CATEGORIES:
            amount *= scenario.fixed_cost_multiplier
        shift = scenario.delay_counterparty.get(e.counterparty_id, 0) if e.counterparty_id else 0
        out.append(replace(e, amount=amount, date=e.date + timedelta(days=shift)))
    return in_hat, out_hat, out + list(scenario.extra_expenses)
