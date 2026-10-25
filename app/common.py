"""Общее для роутеров: страницы, сортировка по белому списку, фильтры, проверка владельца."""
from datetime import date
from decimal import Decimal, InvalidOperation

from psycopg import AsyncConnection

from app.responses import ApiError, not_found_company

MAX_PAGE_SIZE = 100


def page_params(page: str | None, size: str | None) -> tuple[int, int]:
    try:
        page_number = max(int(page or 0), 0)
        page_size = min(max(int(size or 50), 1), MAX_PAGE_SIZE)
    except ValueError:
        raise ApiError(400, "Номер и размер страницы должны быть числами", "page") from None
    return page_number, page_size


def page_dto(items: list, page: int, size: int, total: int) -> dict:
    return {"items": items, "page": page, "size": size, "totalElements": total,
            "totalPages": (total + size - 1) // size}


def order_by(columns: dict[str, str], sort_field: str | None, sort_direction: str | None,
             default: str, tie_breaker: str) -> str:
    """ORDER BY только из белого списка: имя колонки в SQL не подставляется из запроса."""
    if not sort_field:
        return f" ORDER BY {default}"
    column = columns.get(sort_field)
    if column is None:
        raise ApiError(400, "Сортировка по этому полю недоступна", "sortField")
    direction = "DESC" if (sort_direction or "").lower() == "desc" else "ASC"
    return f" ORDER BY {column} {direction} NULLS LAST, {tie_breaker} {direction}"


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Conditions:
    """Накопитель условий WHERE с параметрами (%s): значения всегда идут параметрами, не строкой."""

    def __init__(self, sql: str, params: list):
        self.sql = sql
        self.params = params

    def equal(self, column: str, value: str | None) -> "Conditions":
        if value and value.strip():
            self.sql += f" AND {column} = %s"
            self.params.append(value.strip())
        return self

    def contains(self, column: str, value: str | None) -> "Conditions":
        if value and value.strip():
            self.sql += f" AND {column} ILIKE %s"
            self.params.append("%" + escape_like(value.strip()) + "%")
        return self

    def at_least(self, column: str, value: object | None) -> "Conditions":
        if value is not None:
            self.sql += f" AND {column} >= %s"
            self.params.append(value)
        return self

    def at_most(self, column: str, value: object | None) -> "Conditions":
        if value is not None:
            self.sql += f" AND {column} <= %s"
            self.params.append(value)
        return self


def parse_decimal_filter(value: str | None, field: str) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        result = Decimal(value.strip().replace(",", "."))
    except InvalidOperation:
        raise ApiError(400, "Сумма в фильтре должна быть числом", field) from None
    if not result.is_finite():
        raise ApiError(400, "Сумма в фильтре должна быть числом", field)
    return result


def parse_date_filter(value: str | None, field: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError(400, "Дата в фильтре — в формате ГГГГ-ММ-ДД", field) from None


def counterparty_key(inn: str | None, name: str) -> tuple[str, str]:
    """Один контрагент = пара (ИНН, название); пустой ИНН — '' (как COALESCE(inn, '') в уникальном индексе БД)."""
    return inn or "", name


async def counterparty_ids(conn: AsyncConnection, keys: set[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """id контрагентов по парам (ИНН, название); которых нет — создаются."""
    if not keys:
        return {}
    inns, names = [k[0] for k in keys], [k[1] for k in keys]
    sql = ("SELECT id, COALESCE(inn, '') AS inn, name FROM counterparty "
           "WHERE (COALESCE(inn, ''), name) IN (SELECT * FROM unnest(%s::text[], %s::text[]))")
    ids = {(r["inn"], r["name"]): r["id"] for r in await (await conn.execute(sql, [inns, names])).fetchall()}
    missing = [k for k in keys if k not in ids]
    if missing:
        async with conn.cursor() as cur:
            await cur.executemany("INSERT INTO counterparty (inn, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                  [(inn or None, name) for inn, name in missing])
        # Заодно подхватываем тех, кого параллельно вставила другая загрузка
        ids.update({(r["inn"], r["name"]): r["id"] for r in await (await conn.execute(
            sql, [[k[0] for k in missing], [k[1] for k in missing]])).fetchall()})
    return ids


async def create_session(conn: AsyncConnection, user_id: int) -> int:
    """Сессия загрузки или ручной правки: её id получают все операции этого действия (operation.session_id)."""
    row = await (await conn.execute("INSERT INTO sessions (user_id) VALUES (%s) RETURNING id", [user_id])).fetchone()
    return row["id"]


async def owned_company(conn: AsyncConnection, user_id: int, company_id: str) -> dict:
    """Компания текущего пользователя (есть в users_company) или 404: чужая неотличима от несуществующей."""
    row = await (await conn.execute(
        "SELECT company_id FROM users_company WHERE user_id = %s AND company_id = %s",
        [user_id, company_id])).fetchone()
    if row is None:
        raise not_found_company()
    return row


async def link_companies(conn: AsyncConnection, user_id: int, company_ids: set[str]) -> None:
    """Компании, в которые пользователь добавил данные, становятся его (users_company)."""
    if company_ids:
        await conn.execute(
            "INSERT INTO users_company (user_id, company_id) SELECT %s, unnest(%s::text[]) ON CONFLICT DO NOTHING",
            [user_id, sorted(company_ids)])
