import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("backend.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
# Ключ advisory-lock: несколько воркеров uvicorn не применяют миграции одновременно
MIGRATION_LOCK = 4242


def create_pool(database_url: str) -> AsyncConnectionPool:
    return AsyncConnectionPool(database_url, min_size=1, max_size=10, open=False,
                               kwargs={"row_factory": dict_row}, timeout=10)


async def apply_migrations(pool: AsyncConnectionPool) -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.connection() as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", [MIGRATION_LOCK])
        try:
            for path in files:
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.commit()
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", [MIGRATION_LOCK])
            await conn.commit()
    log.info("migrations applied: %d", len(files))


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    """Соединение на запрос: транзакция коммитится в конце, при исключении — откат."""
    async with request.app.state.pool.connection() as conn:
        yield conn
