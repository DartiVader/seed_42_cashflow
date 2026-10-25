import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection, errors

from app.classification.jobs import classify_session
from app.common import (Conditions, counterparty_ids, counterparty_key, create_session, link_companies, order_by,
                        page_dto, page_params, parse_date_filter, parse_decimal_filter)
from app.db import get_conn
from app.responses import ApiError, ok
from app.schemas import OperationRequest
from app.security import CurrentUser, current_user

log = logging.getLogger("backend.operations")
router = APIRouter(prefix="/api/operations", tags=["operations"])

FROM_SQL = """
    FROM operation o
    JOIN direction d ON d.id = o.direction_id
    LEFT JOIN counterparty cp ON cp.id = o.counterparty_id
    WHERE o.user_id = %s
"""
SELECT_SQL = ("SELECT o.id, o.company_id, o.source_operation_id, o.date, o.amount, d.name AS direction, "
              "cp.inn AS counterparty_inn, cp.name AS counterparty_name, o.payment_purpose")
SORT_COLUMNS = {
    "date": "o.date",
    "companyId": "o.company_id",
    "operationId": "o.source_operation_id",
    "amount": "o.amount",
    "direction": "d.name",
    "counterpartyName": "cp.name",
    "counterpartyInn": "cp.inn",
    "paymentPurpose": "o.payment_purpose",
}


def to_dto(row: dict) -> dict:
    return {"id": row["id"], "companyId": row["company_id"], "operationId": row["source_operation_id"],
            "date": row["date"], "amount": float(row["amount"]), "direction": row["direction"],
            "counterpartyInn": row["counterparty_inn"], "counterpartyName": row["counterparty_name"],
            "paymentPurpose": row["payment_purpose"]}


async def find_or_create_counterparty(conn: AsyncConnection, inn: str | None, name: str) -> int:
    key = counterparty_key(inn, name)
    return (await counterparty_ids(conn, {key}))[key]


async def check_operation(conn: AsyncConnection, user_id: int, body: OperationRequest,
                          current_id: int | None) -> int:
    """Компания есть в справочнике, номер операции её и не занят у пользователя → id направления."""
    company = await (await conn.execute("SELECT 1 FROM company WHERE company_id = %s", [body.companyId])).fetchone()
    if company is None:
        raise ApiError(400, f"Компании {body.companyId} нет — сначала добавьте её", "companyId")
    if not body.operationId.startswith(body.companyId + "-"):
        raise ApiError(400, f"Номер операции должен начинаться с «{body.companyId}-»", "operationId")
    same = await (await conn.execute(
        "SELECT id FROM operation WHERE user_id = %s AND company_id = %s AND source_operation_id = %s",
        [user_id, body.companyId, body.operationId])).fetchone()
    if same is not None and same["id"] != current_id:
        raise ApiError(409, "Операция с таким номером уже есть", "operationId")
    direction = await (await conn.execute("SELECT id FROM direction WHERE name = %s",
                                          [body.direction])).fetchone()
    if direction is None:
        raise ApiError(400, "Направление должно быть «Поступление» или «Списание»", "direction")
    return direction["id"]


async def operation_of_user(conn: AsyncConnection, user_id: int, operation_id: int) -> None:
    row = await (await conn.execute("SELECT 1 " + FROM_SQL + " AND o.id = %s", [user_id, operation_id])).fetchone()
    if row is None:
        raise ApiError(404, "Операция не найдена")


def response_dto(operation_id: int, body: OperationRequest) -> dict:
    return {"id": operation_id, "companyId": body.companyId, "operationId": body.operationId, "date": body.date,
            "amount": float(body.amount), "direction": body.direction, "counterpartyInn": body.counterpartyInn,
            "counterpartyName": body.counterpartyName, "paymentPurpose": body.paymentPurpose}


@router.get("")
async def get_operations(request: Request, page: str | None = None, size: str | None = None,
                         companyId: str | None = None, operationId: str | None = None,
                         counterpartyName: str | None = None, counterpartyInn: str | None = None,
                         paymentPurpose: str | None = None, direction: str | None = None,
                         amountFrom: str | None = None, amountTo: str | None = None,
                         dateFrom: str | None = None, dateTo: str | None = None,
                         sortField: str | None = None, sortDirection: str | None = None,
                         user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    page_number, page_size = page_params(page, size)
    where = (Conditions("", [user.id])
             .equal("o.company_id", companyId)
             .contains("o.source_operation_id", operationId)
             .contains("cp.name", counterpartyName)
             .contains("cp.inn", counterpartyInn)
             .contains("o.payment_purpose", paymentPurpose)
             .equal("d.name", direction)
             .at_least("o.amount", parse_decimal_filter(amountFrom, "amountFrom"))
             .at_most("o.amount", parse_decimal_filter(amountTo, "amountTo"))
             .at_least("o.date", parse_date_filter(dateFrom, "dateFrom"))
             .at_most("o.date", parse_date_filter(dateTo, "dateTo")))
    order = order_by(SORT_COLUMNS, sortField, sortDirection, "o.date DESC, o.id DESC", "o.id")
    rows = await (await conn.execute(SELECT_SQL + FROM_SQL + where.sql + order + " LIMIT %s OFFSET %s",
                                     where.params + [page_size, page_number * page_size])).fetchall()
    total = await (await conn.execute("SELECT count(*) AS n " + FROM_SQL + where.sql, where.params)).fetchone()
    return ok(request, page_dto([to_dto(r) for r in rows], page_number, page_size, total["n"]))


@router.post("", status_code=201)
async def create_operation(request: Request, body: OperationRequest, tasks: BackgroundTasks,
                           user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    direction_id = await check_operation(conn, user.id, body, None)
    counterparty_id = await find_or_create_counterparty(conn, body.counterpartyInn, body.counterpartyName)
    session_id = await create_session(conn, user.id)
    try:
        async with conn.transaction():
            row = await (await conn.execute(
                "INSERT INTO operation (source_operation_id, company_id, date, counterparty_id, amount, direction_id, "
                "payment_purpose, user_id, session_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                [body.operationId, body.companyId, body.date, counterparty_id, body.amount, direction_id,
                 body.paymentPurpose, user.id, session_id])).fetchone()
    except errors.UniqueViolation:
        raise ApiError(409, "Операция с таким номером уже есть", "operationId") from None
    await link_companies(conn, user.id, {body.companyId})
    log.info("operation created user_id=%s company_id=%s", user.id, body.companyId)
    await conn.commit()
    tasks.add_task(classify_session, session_id, None)
    return ok(request, response_dto(row["id"], body), 201)


@router.put("/{operation_id}")
async def update_operation(request: Request, operation_id: int, body: OperationRequest, tasks: BackgroundTasks,
                           user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await operation_of_user(conn, user.id, operation_id)
    direction_id = await check_operation(conn, user.id, body, operation_id)
    counterparty_id = await find_or_create_counterparty(conn, body.counterpartyInn, body.counterpartyName)
    # Правка — новая сессия: категории операции пересчитываются по ней
    session_id = await create_session(conn, user.id)
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE operation SET source_operation_id = %s, company_id = %s, date = %s, counterparty_id = %s, "
                "amount = %s, direction_id = %s, payment_purpose = %s, session_id = %s WHERE id = %s",
                [body.operationId, body.companyId, body.date, counterparty_id, body.amount, direction_id,
                 body.paymentPurpose, session_id, operation_id])
    except errors.UniqueViolation:
        raise ApiError(409, "Операция с таким номером уже есть", "operationId") from None
    await link_companies(conn, user.id, {body.companyId})
    log.info("operation updated user_id=%s operation_id=%s", user.id, operation_id)
    await conn.commit()
    tasks.add_task(classify_session, session_id, None)
    return ok(request, response_dto(operation_id, body))


@router.delete("/{operation_id}")
async def delete_operation(request: Request, operation_id: int, user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await operation_of_user(conn, user.id, operation_id)
    await conn.execute("DELETE FROM operation WHERE id = %s", [operation_id])
    log.info("operation deleted user_id=%s operation_id=%s", user.id, operation_id)
    return ok(request, None)
