"""Холдаут компаний и месячные фолды rolling-origin."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.calendar import last_working_day


def holdout_companies(companies: pd.DataFrame, per_industry: int = 1, seed: int = 42) -> list[str]:
    """По per_industry компаний из каждой отрасли; не участвуют ни в обучении, ни в подборе."""
    rng = np.random.default_rng(seed)
    picked: list[str] = []
    for _, g in companies.sort_values("company_id").groupby("industry", sort=True):
        ids = g["company_id"].to_numpy()
        picked += rng.choice(ids, size=min(per_industry, len(ids)), replace=False).tolist()
    return sorted(picked)


def month_cutoffs(first_cutoff, last_origin) -> list[pd.Timestamp]:
    """Последние рабочие дни месяцев от first_cutoff до месяца перед last_origin."""
    ends = pd.date_range(pd.Timestamp(first_cutoff), pd.Timestamp(last_origin), freq="ME")
    cuts = sorted({last_working_day(d) for d in ends})
    return [c for c in cuts if c < pd.Timestamp(last_origin)]
