"""Подключение маркетплейсов по API-ключу и загрузка их отчётов в операции компании.

Операции отчёта сохраняются тем же путём, что и выписка: сессия, контрагенты, отсев повторов,
затем фоновый расчёт категорий по сессии. Ключи наружу не отдаются — только последние 4 символа.
"""
import hashlib
import logging
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection, errors
from psycopg.types.json import Jsonb

from app.clients.marketplaces import CODES, NAMES, MarketplaceClient, MarketplaceOperation
from app.common import create_session, owned_company
from app.config import Settings, get_settings, marketplace_url
from app.db import get_conn
from app.responses import ApiError, ok
from app.routers.imports import BATCH_SIZE, OperationRow, Report, normalize_inn, RowError, refresh_quality, \
    save_operations, start_classification
from app.schemas import MarketplaceConnectRequest, MarketplaceSyncRequest
from app.security import CurrentUser, current_user

log = logging.getLogger("backend.marketplaces")
router = APIRouter(prefix="/api/marketplaces", tags=["marketplaces"])

MAX_OPERATION_ID = 20  # operation.source_operation_id VARCHAR(20)


def mask(value: str) -> str:
    return "•••• " + value[-4:] if len(value) > 4 else "••••"


def to_dto(row: dict) -> dict:
    creds = row["credentials"]
    key = creds.get("api_key") or creds.get("token") or ""
    return {"id": row["id"], "companyId": row["company_id"], "marketplace": row["marketplace"],
            "marketplaceName": NAMES[row["marketplace"]], "keyMasked": mask(key),
            "clientId": creds.get("client_id"), "businessId": creds.get("business_id"),
            "lastSyncAt": row["last_sync_at"], "lastResult": row["last_result"], "createdAt": row["created_at"]}


def operation_id(company_id: str, marketplace: str, external_id: str) -> str:
    """Номер операции в БД: <company_id>-<префикс><id маркетплейса>, не длиннее 20 символов."""
    value = f"{company_id}-{CODES[marketplace]}{external_id}"
    if len(value) <= MAX_OPERATION_ID:
        return value
    digest = hashlib.sha1(external_id.encode("utf-8")).hexdigest()
    prefix = f"{company_id}-{CODES[marketplace]}"
    return prefix + digest[:MAX_OPERATION_ID - len(prefix)]


def to_row(company_id: str, marketplace: str, index: int, op: MarketplaceOperation) -> OperationRow:
    try:
        inn = normalize_inn(op.counterparty_inn or "")
    except RowError:
        inn = None
    return OperationRow(line=index, company_id=company_id,
                        operation_id=operation_id(company_id, marketplace, op.external_id),
                        date=op.date, amount=op.amount, direction=op.direction, inn=inn,
                        name=op.counterparty_name[:255], purpose=op.payment_purpose, balance_eod=None)


async def connection_of_user(conn: AsyncConnection, user_id: int, connection_id: int) -> dict:
    row = await (await conn.execute("SELECT * FROM marketplace_connection WHERE id = %s AND user_id = %s",
                                    [connection_id, user_id])).fetchone()
    if row is None:
        raise ApiError(404, "Подключение не найдено")
    return row


@router.get("")
async def get_marketplace_connections(request: Request, user: CurrentUser = Depends(current_user),
                                      conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    rows = await (await conn.execute(
        "SELECT * FROM marketplace_connection WHERE user_id = %s ORDER BY company_id, marketplace",
        [user.id])).fetchall()
    return ok(request, [to_dto(r) for r in rows])


@router.post("", status_code=201)
async def connect_marketplace(request: Request, body: MarketplaceConnectRequest,
                              user: CurrentUser = Depends(current_user), conn: AsyncConnection = Depends(get_conn),
                              settings: Settings = Depends(get_settings)) -> JSONResponse:
    await owned_company(conn, user.id, body.companyId)
    credentials = body.credentials()
    # Ключ проверяем пробным запросом до сохранения: неверный ключ → понятная ошибка
    client = MarketplaceClient(request.app.state.http, marketplace_url(settings, body.marketplace),
                               body.marketplace, credentials)
    await client.check()
    try:
        async with conn.transaction():
            row = await (await conn.execute(
                "INSERT INTO marketplace_connection (user_id, company_id, marketplace, credentials) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                [user.id, body.companyId, body.marketplace, Jsonb(credentials)])).fetchone()
    except errors.UniqueViolation:
        raise ApiError(409, f"{NAMES[body.marketplace]} уже подключён к этой компании", "marketplace") from None
    log.info("marketplace connected user_id=%s company_id=%s marketplace=%s", user.id, body.companyId,
             body.marketplace)
    return ok(request, to_dto(row), 201)


@router.delete("/{connection_id}")
async def disconnect_marketplace(request: Request, connection_id: int, user: CurrentUser = Depends(current_user),
                                 conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    row = await connection_of_user(conn, user.id, connection_id)
    await conn.execute("DELETE FROM marketplace_connection WHERE id = %s", [connection_id])
    log.info("marketplace disconnected user_id=%s company_id=%s marketplace=%s", user.id, row["company_id"],
             row["marketplace"])
    return ok(request, None)


@router.post("/{connection_id}/sync")
async def sync_marketplace(request: Request, connection_id: int, body: MarketplaceSyncRequest,
                           tasks: BackgroundTasks, user: CurrentUser = Depends(current_user),
                           conn: AsyncConnection = Depends(get_conn),
                           settings: Settings = Depends(get_settings)) -> JSONResponse:
    started = time.perf_counter()
    row = await connection_of_user(conn, user.id, connection_id)
    company_id, marketplace = row["company_id"], row["marketplace"]
    client = MarketplaceClient(request.app.state.http, marketplace_url(settings, marketplace), marketplace,
                               row["credentials"])
    operations = await client.fetch(body.dateFrom, body.dateTo)

    session_id = await create_session(conn, user.id)
    report = Report("OPERATIONS")
    rows = [to_row(company_id, marketplace, index, op) for index, op in enumerate(operations, start=1)
            if op.amount > 0]
    report.total = len(operations)
    report.skipped += len(operations) - len(rows)  # нулевые суммы операцией не считаем
    first_days: dict = {}  # остатка в отчётах маркетплейсов нет — opening_balance компании не трогаем
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        sub = Report("OPERATIONS")
        async with conn.transaction():
            await save_operations(conn, user.id, session_id, batch, sub, first_days)
        report.merge(sub)

    result = {"dateFrom": body.dateFrom, "dateTo": body.dateTo, "total": report.total,
              "accepted": report.accepted, "skipped": report.skipped, "rejected": report.rejected}
    await conn.execute(
        "UPDATE marketplace_connection SET last_sync_at = %s, last_result = %s WHERE id = %s",
        [datetime.now().astimezone(), Jsonb({k: str(v) if k.startswith("date") else v for k, v in result.items()}),
         connection_id])
    log.info("marketplace synced user_id=%s company_id=%s marketplace=%s total=%d accepted=%d skipped=%d "
             "rejected=%d took_ms=%d", user.id, company_id, marketplace, report.total, report.accepted,
             report.skipped, report.rejected, (time.perf_counter() - started) * 1000)
    classifying = await start_classification(conn, tasks, session_id, body.asOf, report.accepted)
    refresh_quality(tasks, request, user, report.accepted)
    return ok(request, {**result, "errors": report.errors, "companyId": company_id, "marketplace": marketplace,
                        "sessionId": session_id, "classifying": classifying})
