import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.clients.llm import LlmClient
from app.clients.ml import MlClient
from app.config import Settings, get_settings
from app.context import request_id_var
from app.db import apply_migrations, create_pool
from app.responses import ApiError, fail
from app.routers import admin, auth, companies, forecast, imports, marketplaces, operations, quality, users
from app.schemas import DEFAULT_MESSAGE, FIELD_MESSAGES

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def upload_limits_mb(settings: Settings) -> dict[str, int]:
    return {"/api/imports": settings.max_upload_mb, "/api/imports/dataset": settings.max_dataset_mb}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(f, RequestIdFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"))
        root.addHandler(handler)
    # Свой access-лог пишем сами (путь без query: в фильтрах бывают ИНН и суммы); у httpx в URL — тоже query
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


log = logging.getLogger("backend")


async def ensure_admin(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        log.warning("ADMIN_EMAIL or ADMIN_PASSWORD is not set, admin user is not created")
        return
    async with app.state.pool.connection() as conn:
        row = await (await conn.execute("SELECT id FROM users WHERE email = %s",
                                        [auth.normalize_email(settings.admin_email)])).fetchone()
        if row is None:
            await auth.create_user(conn, settings.admin_email, settings.admin_password, True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is not set")
    app.state.pool = create_pool(settings.database_url)
    await app.state.pool.open(wait=True, timeout=30)
    await apply_migrations(app.state.pool)
    await ensure_admin(app)
    # Один общий клиент на приложение; таймауты задаются на каждый вызов (clients/*.py)
    app.state.http = httpx.AsyncClient(limits=httpx.Limits(max_connections=50))
    app.state.ml = MlClient(app.state.http, settings.ml_url, settings.ml_internal_token)
    app.state.llm = LlmClient(app.state.http, settings.llm_url, settings.llm_internal_token)
    yield
    await app.state.http.aclose()
    await app.state.pool.close()


app = FastAPI(title="Seed 42 backend", lifespan=lifespan)
for module in (auth, users, companies, operations, imports, marketplaces, forecast, quality, admin):
    app.include_router(module.router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """X-Request-ID, лимит размера загрузки и короткий access-лог (метод, путь, статус, время, user_id)."""
    header = request.headers.get("X-Request-ID", "")
    request_id = header if SAFE_REQUEST_ID.match(header) else str(uuid.uuid4())
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        settings = get_settings()
        limit_mb = upload_limits_mb(settings).get(request.url.path)
        length = request.headers.get("content-length")
        if limit_mb and length and length.isdigit() and int(length) > limit_mb * 1024 * 1024 + 64 * 1024:
            response = fail(request, 413, [{"field": "file",
                                            "message": f"Файл больше {limit_mb} МБ, разделите его на части"}])
        else:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001
                # Только тип исключения, без трейса: в тексте ошибок драйвера бывают значения из запроса
                log.error("unhandled exception: %s", type(exc).__name__)
                response = fail(request, 500, [{"field": None, "message": "Что-то пошло не так, попробуйте ещё раз"}])
        response.headers["X-Request-ID"] = request_id
        log.info("%s %s status=%d user_id=%s took_ms=%d", request.method, request.url.path, response.status_code,
                 getattr(request.state, "user_id", None), (time.perf_counter() - started) * 1000)
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return fail(request, exc.status, exc.errors)


def validation_errors(exc: RequestValidationError) -> list[dict]:
    """Ошибки pydantic → [{field, message}] по-русски. Значения из запроса (input) в ответ не попадают."""
    result = []
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", ())]
        if err.get("type") == "json_invalid" or loc in (["body"], []):
            return [{"field": None, "message": "Не удалось прочитать данные запроса"}]
        name = loc[1] if len(loc) > 1 else loc[0]
        if err.get("type") == "ru":
            message = err["msg"]
        else:
            message = FIELD_MESSAGES.get(name, DEFAULT_MESSAGE)
        item = {"field": name, "message": message}
        if item not in result:
            result.append(item)
    return result


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return fail(request, 400, validation_errors(exc))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    messages = {404: "Такой страницы нет", 405: "Этот метод запроса не поддерживается"}
    return fail(request, exc.status_code,
                [{"field": None, "message": messages.get(exc.status_code, "Запрос не выполнен")}])


@app.exception_handler(pg_errors.OperationalError)
async def db_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("database unavailable: %s", type(exc).__name__)
    return fail(request, 503, [{"field": None, "message": "База данных недоступна, попробуйте через минуту"}])


@app.get("/health")
async def health(request: Request) -> dict:
    db_ok = True
    try:
        async with request.app.state.pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
    except Exception:  # noqa: BLE001 — health не падает, а сообщает
        db_ok = False
    ml_ok = await request.app.state.ml.health()
    llm_ok = await request.app.state.llm.health()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "ml": ml_ok, "llm": llm_ok}
