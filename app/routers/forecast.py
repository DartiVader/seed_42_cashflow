"""Прогноз, объяснение и план-факт: проверка владельца, перевод camelCase → snake_case, прокси в ML и LLM."""
import logging
import time
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection

from app.common import owned_company
from app.db import get_conn
from app.responses import ApiError, ok
from app.schemas import ExplainRequest, ForecastRequest
from app.security import CurrentUser, current_user

log = logging.getLogger("backend.forecast")
router = APIRouter(prefix="/api/companies", tags=["forecast"])

ML_SOURCES = {"invoice", "contract", "manual", "bank", "tax"}
# counterparty_name, label, overdue_from ML игнорирует — не шлём
EVENT_FIELDS = ("date", "amount", "category", "source", "confidence", "mandatory", "stream_id", "counterparty_id")
REVENUE_RANGE = (0.3, 1.5)
FIXED_COST_RANGE = (0.5, 2.0)
SEED = 42


def to_ml_event(event: Any) -> dict:
    if not isinstance(event, dict):
        raise ApiError(400, "Список платежей передан в неверном формате", "events")
    result = {k: event[k] for k in EVENT_FIELDS if event.get(k) is not None}
    result.setdefault("category", "other")  # у шлюза category обязательна
    # regular / history приходят, когда пользователь применил совет или поправил найденный платёж
    if result.get("source") not in ML_SOURCES:
        result["source"] = "manual"
    return result


def number_in(value: Any, low: float, high: float, message: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ApiError(400, message, "scenario")
    return value


def to_ml_scenario(scenario: dict) -> dict:
    result: dict[str, Any] = {}
    revenue = number_in(scenario.get("revenue_multiplier"), *REVENUE_RANGE,
                        "Выручка в сценарии — от 30% до 150% от обычной")
    fixed = number_in(scenario.get("fixed_cost_multiplier"), *FIXED_COST_RANGE,
                      "Постоянные расходы в сценарии — от 50% до 200% от обычных")
    if revenue is not None:
        result["revenue_multiplier"] = revenue
    if fixed is not None:
        result["fixed_cost_multiplier"] = fixed
    delays = scenario.get("delay_counterparty") or {}
    if not isinstance(delays, dict) or not all(
            isinstance(v, int) and not isinstance(v, bool) and -365 <= v <= 365 for v in delays.values()):
        raise ApiError(400, "Сдвиг платежа контрагента — целое число дней", "scenario")
    if delays:
        result["delay_counterparty"] = {str(k): v for k, v in delays.items()}
    extra = scenario.get("extra_expenses") or []
    if not isinstance(extra, list):
        raise ApiError(400, "Дополнительные расходы в сценарии переданы в неверном формате", "scenario")
    if extra:
        result["extra_expenses"] = [to_ml_event(e) for e in extra]
    return result


def to_ml_request(body: ForecastRequest, opening_balance: float, operations: list[dict]) -> dict:
    request = {
        "as_of": body.asOf.isoformat(),
        "horizon_days": body.horizonDays,
        "threshold": body.threshold,
        "seed": SEED,
        "advice": True,
        # Остаток на начало выписки: без него ML считает остаток от нуля и весь прогноз сдвинут
        "opening_balance": opening_balance,
        "period_from": None,
        "period_to": None,
        "industry": None,  # ML сам берёт company.industry
        "events": [to_ml_event(e) for e in body.events],
        # История компании из БД (get_operations_period): остаток на конец дня и признаки категорий
        "operations": operations,
    }
    if body.scenario:
        request["scenario"] = to_ml_scenario(body.scenario)
    if body.trace:
        request["trace"] = True
    return request


# Начало истории для get_operations_period: функция берёт остаток на эту дату как opening_balance
# плюс все операции до неё, поэтому раньше любой выписки — значит вся история
HISTORY_START = date(2000, 1, 1)


async def opening_balance_of(conn: AsyncConnection, company_id: str) -> float:
    """Остаток на начало первого дня выписки (считается при импорте); без выписки — ноль."""
    row = await (await conn.execute("SELECT opening_balance FROM company WHERE company_id = %s",
                                    [company_id])).fetchone()
    return float(row["opening_balance"]) if row and row["opening_balance"] is not None else 0.0


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


async def operations_of(conn: AsyncConnection, company_id: str, user_id: int, as_of: date) -> list[dict]:
    """Операции пользователя по компании по дату прогноза включительно — функцией БД get_operations_period."""
    # MATERIALIZED: функция считается отдельно (операции компании), потом фильтр по пользователю.
    # Без него Postgres встраивает тело функции в запрос и на сотнях тысяч операций выбирает план на минуты
    rows = await (await conn.execute(
        "WITH p AS MATERIALIZED (SELECT * FROM get_operations_period(%s, %s, %s)) "
        "SELECT p.* FROM p JOIN operation o ON o.id = p.operation_id WHERE o.user_id = %s "
        "ORDER BY p.operation_date, p.operation_id",
        [company_id, HISTORY_START, as_of, user_id])).fetchall()
    return [{key: jsonable(value) for key, value in row.items()} for row in rows]


@router.post("/{company_id}/forecast")
async def forecast(request: Request, company_id: str, body: ForecastRequest,
                   user: CurrentUser = Depends(current_user),
                   conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await owned_company(conn, user.id, company_id)
    ml_request = to_ml_request(body, await opening_balance_of(conn, company_id),
                               await operations_of(conn, company_id, user.id, body.asOf))
    started = time.perf_counter()
    status = "error"
    try:
        result = await request.app.state.ml.forecast(company_id, user.id, ml_request)
        status = "ok"
    except ApiError as exc:
        status = str(exc.status)
        raise
    finally:
        log.info("forecast user_id=%s company_id=%s scenario=%s events=%d operations=%d status=%s took_ms=%d",
                 user.id, company_id, "scenario" in ml_request, len(ml_request["events"]),
                 len(ml_request["operations"]), status,
                 (time.perf_counter() - started) * 1000)
    return ok(request, result)


@router.post("/{company_id}/explain")
async def explain(request: Request, company_id: str, body: ExplainRequest,
                  user: CurrentUser = Depends(current_user),
                  conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await owned_company(conn, user.id, company_id)
    started = time.perf_counter()
    result = await request.app.state.llm.explain(
        {"kind": body.kind, "forecast": body.forecast, "base": body.base, "question": body.question})
    log.info("explain user_id=%s company_id=%s kind=%s source=%s took_ms=%d", user.id, company_id, body.kind,
             result.get("source") if isinstance(result, dict) else None, (time.perf_counter() - started) * 1000)
    return ok(request, result)


@router.get("/{company_id}/plan-fact")
async def plan_fact(request: Request, company_id: str, asOf: str | None = None, lookbackDays: str | None = None,
                    user: CurrentUser = Depends(current_user),
                    conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await owned_company(conn, user.id, company_id)
    try:
        as_of = date.fromisoformat((asOf or "").strip())
    except ValueError:
        raise ApiError(400, "Укажите дату в формате ГГГГ-ММ-ДД", "asOf") from None
    try:
        lookback = int(lookbackDays) if lookbackDays not in (None, "") else 10
    except ValueError:
        lookback = 0
    if not 1 <= lookback <= 60:
        raise ApiError(400, "Период сверки — от 1 до 60 рабочих дней", "lookbackDays")
    started = time.perf_counter()
    result = await request.app.state.ml.plan_fact(company_id, user.id, as_of.isoformat(), lookback,
                                                  await opening_balance_of(conn, company_id))
    log.info("plan_fact user_id=%s company_id=%s took_ms=%d", user.id, company_id,
             (time.perf_counter() - started) * 1000)
    return ok(request, result)
