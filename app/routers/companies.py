import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection

from app.common import Conditions, link_companies, order_by, owned_company, page_dto, page_params
from app.db import get_conn
from app.responses import ApiError, ok
from app.schemas import CompanyRequest
from app.security import CurrentUser, current_user

log = logging.getLogger("backend.companies")
router = APIRouter(prefix="/api/companies", tags=["companies"])

# Компании пользователя — через users_company: сама компания общая, данные в ней у каждого свои
FROM_SQL = ("FROM company c JOIN users_company uc ON uc.company_id = c.company_id "
            "LEFT JOIN legal_form lf ON lf.id = c.legal_form_id WHERE uc.user_id = %s")
SELECT_SQL = "SELECT c.company_id, c.company_name, c.company_inn, lf.code AS legal_form, c.industry " + FROM_SQL
SORT_COLUMNS = {
    "companyId": "c.company_id",
    "companyName": "c.company_name",
    "companyInn": "c.company_inn",
    "legalForm": "lf.code",
    "industry": "c.industry",
}


def to_dto(row: dict) -> dict:
    return {"companyId": row["company_id"], "companyName": row["company_name"], "companyInn": row["company_inn"],
            "legalForm": row["legal_form"], "industry": row["industry"]}


async def legal_forms(conn: AsyncConnection) -> dict[str, dict]:
    rows = await (await conn.execute("SELECT id, code, inn_length FROM legal_form")).fetchall()
    return {r["code"]: r for r in rows}


async def check_company(conn: AsyncConnection, body: CompanyRequest, company_id: str) -> int:
    """Форма и длина ИНН, ИНН не занят другой компанией → id формы."""
    form = (await legal_forms(conn)).get(body.legalForm)
    if form is None:
        raise ApiError(400, "Форма должна быть ООО или ИП", "legalForm")
    if len(body.companyInn) != form["inn_length"]:
        raise ApiError(400, f"У {form['code']} ИНН из {form['inn_length']} цифр", "companyInn")
    other = await (await conn.execute("SELECT company_id FROM company WHERE company_inn = %s AND company_id <> %s",
                                      [body.companyInn, company_id])).fetchone()
    if other is not None:
        raise ApiError(409, "Этот ИНН уже указан у другой компании", "companyInn")
    return form["id"]


@router.get("")
async def get_companies(request: Request, page: str | None = None, size: str | None = None,
                        companyId: str | None = None, companyName: str | None = None, companyInn: str | None = None,
                        legalForm: str | None = None, industry: str | None = None,
                        sortField: str | None = None, sortDirection: str | None = None,
                        user: CurrentUser = Depends(current_user),
                        conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    page_number, page_size = page_params(page, size)
    where = (Conditions("", [user.id])
             .contains("c.company_id", companyId)
             .contains("c.company_name", companyName)
             .contains("c.company_inn", companyInn)
             .equal("lf.code", legalForm)
             .equal("c.industry", industry))
    order = order_by(SORT_COLUMNS, sortField, sortDirection, "c.company_id", "c.company_id")
    rows = await (await conn.execute(SELECT_SQL + where.sql + order + " LIMIT %s OFFSET %s",
                                     where.params + [page_size, page_number * page_size])).fetchall()
    total = await (await conn.execute("SELECT count(*) AS n " + FROM_SQL + where.sql, where.params)).fetchone()
    return ok(request, page_dto([to_dto(r) for r in rows], page_number, page_size, total["n"]))


@router.get("/all")
async def get_all_companies(request: Request, user: CurrentUser = Depends(current_user),
                            conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    rows = await (await conn.execute(SELECT_SQL + " ORDER BY c.company_id", [user.id])).fetchall()
    return ok(request, [to_dto(r) for r in rows])


@router.post("", status_code=201)
async def create_company(request: Request, body: CompanyRequest, user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    exists = await (await conn.execute("SELECT 1 FROM company WHERE company_id = %s", [body.companyId])).fetchone()
    if exists:
        raise ApiError(409, "Компания с таким кодом уже есть", "companyId")
    form_id = await check_company(conn, body, body.companyId)
    await conn.execute(
        "INSERT INTO company (company_id, company_name, company_inn, legal_form_id, industry) "
        "VALUES (%s, %s, %s, %s, %s)",
        [body.companyId, body.companyName, body.companyInn, form_id, body.industry])
    await link_companies(conn, user.id, {body.companyId})
    log.info("company created user_id=%s company_id=%s", user.id, body.companyId)
    return ok(request, body.model_dump(), 201)


@router.put("/{company_id}")
async def update_company(request: Request, company_id: str, body: CompanyRequest,
                         user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await owned_company(conn, user.id, company_id)
    form_id = await check_company(conn, body, company_id)
    await conn.execute(
        "UPDATE company SET company_name = %s, company_inn = %s, legal_form_id = %s, industry = %s "
        "WHERE company_id = %s",
        [body.companyName, body.companyInn, form_id, body.industry, company_id])
    log.info("company updated user_id=%s company_id=%s", user.id, company_id)
    return ok(request, {**body.model_dump(), "companyId": company_id})


@router.delete("/{company_id}")
async def delete_company(request: Request, company_id: str, user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    await owned_company(conn, user.id, company_id)
    # Удаляем данные пользователя по компании; саму компанию — когда она больше ни у кого не осталась
    await conn.execute("DELETE FROM operation WHERE company_id = %s AND user_id = %s", [company_id, user.id])
    await conn.execute("DELETE FROM marketplace_connection WHERE company_id = %s AND user_id = %s",
                       [company_id, user.id])
    await conn.execute("DELETE FROM users_company WHERE company_id = %s AND user_id = %s", [company_id, user.id])
    await conn.execute(
        "DELETE FROM company c WHERE c.company_id = %s "
        "AND NOT EXISTS (SELECT 1 FROM users_company uc WHERE uc.company_id = c.company_id) "
        "AND NOT EXISTS (SELECT 1 FROM operation o WHERE o.company_id = c.company_id)", [company_id])
    log.info("company deleted user_id=%s company_id=%s", user.id, company_id)
    return ok(request, None)
