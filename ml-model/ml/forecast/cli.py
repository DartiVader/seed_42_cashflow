"""Прогноз одной компании в контрактный JSON.

    python -m ml.forecast.cli C001 2026-09-30 [--horizon 30] [--revenue 0.7] [--model lgbm]
    python -m ml.forecast.cli C044 2026-09-30 --plan-fact [--lookback 10]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

from ml.forecast.api import DEFAULT_MODEL, DEFAULT_VERSION, ForecastContext, forecast
from ml.forecast.contracts import ForecastError, Scenario


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("company_id")
    ap.add_argument("as_of", type=date.fromisoformat)
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--revenue", type=float, default=1.0, help="сценарий: множитель выручки")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data", default=os.environ.get("ML_DATA_DIR", "cashflow_data/cashflow_dataset_participants"))
    ap.add_argument("--models-dir", default=os.environ.get("ML_MODELS_DIR", "models"))
    ap.add_argument("--model", default=DEFAULT_MODEL, help="lgbm_net (основная) или lgbm (резерв)")
    ap.add_argument("--version", default=DEFAULT_VERSION, help="v2 — с регулярными событиями, v1 — без")
    ap.add_argument("--residuals", default="reports/backtest_residuals.parquet")
    ap.add_argument("--plan-fact", action="store_true", help="план-факт вместо прогноза (ml.forecast.plan_fact)")
    ap.add_argument("--lookback", type=int, default=10, help="план-факт: рабочих дней назад")
    args = ap.parse_args(argv)

    ctx = ForecastContext.load(args.data, args.models_dir, args.residuals, model=args.model,
                               version=args.version if args.model == 'lgbm_net' else 'v1')
    scenario = Scenario(revenue_multiplier=args.revenue) if args.revenue != 1.0 else None
    try:
        if args.plan_fact:
            from ml.forecast.plan_fact import plan_fact
            out = plan_fact(args.company_id, args.as_of, args.lookback, seed=args.seed, context=ctx)
        else:
            out = forecast(args.company_id, args.as_of, args.horizon, scenario=scenario, seed=args.seed,
                           context=ctx).to_dict()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except ForecastError as e:
        print(json.dumps({"company_id": args.company_id, "error": str(e)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
