"""ML-сервис Seed 42: FastAPI-шлюз + пулы процессов-воркеров. Контракт — ML_API_CONTRACT.md.

Шлюз ничего не считает: проверяет токен и запрос, кладёт расчёт в пул воркеров (у каждого свой
ForecastContext), отдаёт результат. Тяжёлые задачи (process, retrain) идут в отдельный пул через
очередь в ml_jobs. Запуск: uvicorn service.main:app (из корня server/, один процесс — воркеры порождает он сам).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import multiprocessing as mp
import secrets
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ml.forecast.contracts import ForecastError
from ml.pipeline.regular import CATEGORIES
from service import quality, registry, workers
from service.config import Settings, get_settings
from service.db import DatabaseUnavailableError, company_exists, db_enabled
from service.errors import ApiError, company_not_found, from_forecast_error
from service.schemas import CategoryIn, ForecastIn, ProcessIn
from service.store import Store

log = logging.getLogger("ml.api")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
HEALTH_PATH = "/ml/health"


class State:
    """Изменяемое состояние процесса-шлюза."""
    settings: Settings
    store: Store
    pool: ProcessPoolExecutor
    job_pool: ProcessPoolExecutor
    companies: pd.DataFrame
    model_loaded: bool = False
    model_version: str
    pending: int = 0          # запросов в пуле прогноза: исполняются + ждут


S = State()


def _make_pool(n: int, init=None, args=()) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn"), initializer=init, initargs=args)


def _make_forecast_pool() -> ProcessPoolExecutor:
    s = S.settings
    return _make_pool(s.workers, workers.init_worker,
                      (str(s.data_dir), str(s.models_dir), str(s.reports_dir), S.model_version))


async def _warmup() -> None:
    """Воркеры грузят контекст при старте; ping возвращается, когда загрузка закончилась."""
    loop = asyncio.get_running_loop()
    try:
        await asyncio.gather(*[loop.run_in_executor(S.pool, workers.ping, S.model_version)
                               for _ in range(S.settings.workers)])
        S.model_loaded = True
        log.info("workers ready n=%d version=%s", S.settings.workers, S.model_version)
    except Exception:                                                         # noqa: BLE001
        log.exception("workers failed to start")
        S.model_loaded = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    S.settings = s = get_settings()
    if not s.internal_token and not s.auth_disabled:
        log.warning("INTERNAL_TOKEN не задан — все вызовы, кроме /ml/health, получат 401")
    S.store = Store(s.db_path)
    S.store.fail_stale_jobs()
    S.model_version = registry.active_version(S.store, s.default_model)
    S.companies = pd.read_csv(s.data_dir / "companies.csv", sep=";", encoding="utf-8-sig", dtype={"company_inn": str})
    S.pool = _make_forecast_pool()
    S.job_pool = _make_pool(s.job_workers)
    warm = asyncio.create_task(_warmup())
    yield
    warm.cancel()
    S.pool.shutdown(wait=False, cancel_futures=True)
    S.job_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Seed 42 ML service", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ сквозное: request id, авторизация, ошибки

@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    t = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    # в логи: метод, путь (company_id в нём есть, остального нет), статус, время
    log.info("request_id=%s %s %s -> %d %.0fms", rid, request.method, request.url.path, response.status_code,
             (time.perf_counter() - t) * 1000)
    return response


def auth(x_internal_token: str | None = Header(default=None)) -> None:
    s = S.settings
    if s.auth_disabled:
        return
    if not s.internal_token or not x_internal_token or not secrets.compare_digest(x_internal_token, s.internal_token):
        raise ApiError(401, "unauthorized", "Неверный внутренний токен.")


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, e: ApiError):
    return _err(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, e: RequestValidationError):
    fields = ", ".join(sorted({".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]) for err in e.errors()}))
    return _err(400, "bad_request", f"Неверный запрос: проверьте поля ({fields}). Горизонт прогноза — от 7 до 90 дней.")


@app.exception_handler(StarletteHTTPException)
async def http_handler(_: Request, e: StarletteHTTPException):
    return _err(e.status_code, "not_found" if e.status_code == 404 else "http_error", "Такого метода нет.")


@app.exception_handler(Exception)
async def unhandled(_: Request, e: Exception):
    log.error("unhandled %s", type(e).__name__)
    return _err(500, "internal_error", "Внутренняя ошибка сервиса прогноза. Попробуйте позже.")


# ------------------------------------------------------------------ вспомогательное

def known_company(company_id: str) -> None:
    """Компания есть в датасете или (если подключена БД) в таблице company."""
    if (S.companies["company_id"] == company_id).any():
        return
    try:
        if db_enabled() and company_exists(company_id):
            return
    except DatabaseUnavailableError:
        raise ApiError(503, "db_unavailable", "Сервис прогноза сейчас недоступен.")
    raise company_not_found()


async def in_pool(fn, *args):
    """Расчёт в пуле воркеров: 429 при переполнении очереди, 503 если модель не загружена или воркер упал."""
    s = S.settings
    if not S.model_loaded:
        raise ApiError(503, "model_not_loaded", "Сервис прогноза сейчас недоступен.")
    if S.pending >= s.workers + s.queue_max:
        raise ApiError(429, "busy", "Сервис прогноза перегружен. Повторите запрос через несколько секунд.")
    S.pending += 1
    try:
        return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(S.pool, fn, *args),
                                      s.request_timeout_s)
    except ForecastError as e:
        raise from_forecast_error(e)
    except DatabaseUnavailableError:
        raise ApiError(503, "db_unavailable", "Сервис прогноза сейчас недоступен.")
    except asyncio.TimeoutError:
        raise ApiError(503, "timeout", "Сервис прогноза сейчас недоступен.")
    except BrokenProcessPool:
        S.model_loaded = False
        S.pool = _make_forecast_pool()                    # упавший воркер: пересоздаём пул и греем заново
        asyncio.create_task(_warmup())
        raise ApiError(503, "worker_crashed", "Сервис прогноза сейчас недоступен.")
    finally:
        S.pending -= 1


def _job_json(j: dict) -> dict:
    return {"job_id": j["job_id"], "company_id": j["company_id"], "kind": j["kind"], "status": j["status"],
            "progress": round(j["progress"], 2), "stage": j["stage"], "started_at": j["started_at"],
            "finished_at": j["finished_at"], "error": j["error"]}


def _submit_job(fn, *args) -> None:
    try:
        S.job_pool.submit(fn, *args)
    except BrokenProcessPool:
        global_job_pool_reset()
        S.job_pool.submit(fn, *args)


def global_job_pool_reset() -> None:
    S.job_pool = _make_pool(S.settings.job_workers)


# ------------------------------------------------------------------ 1. служебные

@app.get(HEALTH_PATH)
async def health() -> dict:
    s = S.settings
    queue = max(0, S.pending - s.workers)
    status = "down" if not hasattr(S, "pool") else ("ok" if S.model_loaded and queue < s.queue_max else "degraded")
    return {"status": status, "model_loaded": S.model_loaded, "model_version": S.model_version,
            "workers": s.workers, "queue": queue}


@app.get("/ml/version", dependencies=[Depends(auth)])
async def version() -> dict:
    s = S.settings
    tr = s.models_dir / S.model_version / "training.json"
    trained = json.loads(tr.read_text(encoding="utf-8")).get("trained_until") if tr.exists() else None
    return {"service": s.service_version, "contract": s.contract_version, "model_version": S.model_version,
            "trained_at": trained, "data_until": str(S.companies["last_operation_date"].max())}


# ------------------------------------------------------------------ 2-3. прогноз и план-факт

@app.post("/ml/companies/{company_id}/forecast", dependencies=[Depends(auth)])
async def post_forecast(company_id: str, body: ForecastIn, user_id: int | None = None) -> dict:
    # user_id — операции только этого пользователя компании (из БД); без него — все операции компании
    known_company(company_id)
    req = json.loads(body.model_dump_json())
    return await in_pool(workers.run_forecast, S.model_version, company_id, req, user_id)


@app.get("/ml/companies/{company_id}/plan-fact", dependencies=[Depends(auth)])
async def get_plan_fact(company_id: str, as_of: date, lookback_days: int = Query(10, ge=1, le=60),
                        user_id: int | None = None) -> dict:
    known_company(company_id)
    return await in_pool(workers.run_plan_fact, S.model_version, company_id, as_of.isoformat(), lookback_days,
                         user_id)


# ------------------------------------------------------------------ 4. process / jobs / status

@app.post("/ml/companies/{company_id}/process", status_code=202, dependencies=[Depends(auth)])
async def post_process(company_id: str, body: ProcessIn) -> dict:
    known_company(company_id)
    job_id, created = S.store.create_job("process", company_id, json.loads(body.model_dump_json()), dedupe=True)
    if created:
        _submit_job(workers.run_process_job, str(S.settings.db_path), job_id, str(S.settings.data_dir))
    return {"job_id": job_id, "status": "queued", "position": S.store.queue_position(job_id)}


@app.get("/ml/jobs/{job_id}", dependencies=[Depends(auth)])
async def get_job(job_id: str) -> dict:
    j = S.store.get_job(job_id)
    if not j:
        raise ApiError(404, "job_not_found", "Задача не найдена.")
    return _job_json(j)


@app.get("/ml/companies/{company_id}/status", dependencies=[Depends(auth)])
async def get_status(company_id: str) -> dict:
    known_company(company_id)
    row = S.companies[S.companies["company_id"] == company_id].iloc[0]
    job = S.store.last_done_job(company_id)
    # данные компании уже есть в датасете ML — прогноз доступен и без process
    return {"company_id": company_id, "ready": True, "last_job_id": job["job_id"] if job else None,
            "data_until": str(row["last_operation_date"]),
            "operations": S.store.count_operations(company_id) or int(row["operations_count"])}


# ------------------------------------------------------------------ 6. категории и потоки

def _processed(company_id: str) -> None:
    known_company(company_id)
    if not S.store.count_operations(company_id):
        raise ApiError(422, "not_processed", "Операции компании ещё не обработаны. Загрузите выписку.")


@app.get("/ml/companies/{company_id}/operations", dependencies=[Depends(auth)])
async def get_operations(company_id: str, from_: date | None = Query(None, alias="from"), to: date | None = None,
                         limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)) -> dict:
    _processed(company_id)
    total, rows = S.store.operations(company_id, from_.isoformat() if from_ else None,
                                     to.isoformat() if to else None, limit, offset)
    return {"total": total, "items": [
        {"operation_id": r["operation_id"], "date": r["operation_date"], "amount": r["amount"],
         "category": r["category"], "category_confidence": r["category_confidence"],
         "category_source": r["category_source"], "mandatory": bool(r["mandatory"]), "regular": bool(r["regular"]),
         "stream_id": r["stream_id"]} for r in rows]}


@app.put("/ml/companies/{company_id}/operations/{operation_id}/category", dependencies=[Depends(auth)])
async def put_category(company_id: str, operation_id: str, body: CategoryIn) -> dict:
    _processed(company_id)
    if body.category not in CATEGORIES:
        raise ApiError(400, "unknown_category", "Такой категории нет. Выберите категорию из списка.")
    if not S.store.set_manual_category(company_id, operation_id, body.category):
        raise ApiError(404, "operation_not_found", "Операция не найдена.")
    job_id, created = S.store.create_job("process", company_id, {"reason": "recategorize"}, dedupe=True)
    if created:
        _submit_job(workers.run_process_job, str(S.settings.db_path), job_id, str(S.settings.data_dir))
    return {"ok": True, "job_id": job_id}


@app.get("/ml/companies/{company_id}/streams", dependencies=[Depends(auth)])
async def get_streams(company_id: str) -> list[dict]:
    _processed(company_id)
    return S.store.streams(company_id)


# ------------------------------------------------------------------ 7. модели

@app.get("/ml/models", dependencies=[Depends(auth)])
async def get_models() -> list[dict]:
    s = S.settings
    return registry.describe(S.store, s.models_dir, s.reports_dir, s.default_model)


@app.post("/ml/models/retrain", status_code=202, dependencies=[Depends(auth)])
async def post_retrain() -> dict:
    s = S.settings
    job_id, created = S.store.create_job("retrain", None, dedupe=True)
    if created:
        _submit_job(registry.run_retrain_job, str(s.db_path), job_id, str(s.data_dir), str(s.models_dir),
                    str(s.state_dir))
    return {"job_id": job_id}


# ------------------------------------------------------------------ отчёт о качестве по компаниям администраторов

@app.post("/ml/quality/run", status_code=202, dependencies=[Depends(auth)])
async def post_quality_run() -> dict:
    """Контрольный прогон по компаниям, загруженным администраторами (из БД). Повторный запрос, пока задача в
    очереди, возвращает её же."""
    if not db_enabled():
        raise ApiError(503, "db_unavailable", "Отчёт о качестве считается по данным из БД, а она не подключена.")
    s = S.settings
    job_id, created = S.store.create_job("quality", None, dedupe=True)
    if created:
        _submit_job(quality.run_quality_job, str(s.db_path), job_id, str(s.state_dir), s.quality_workers)
    return {"job_id": job_id}


@app.get("/ml/quality", dependencies=[Depends(auth)])
async def get_quality() -> dict:
    """Последний готовый отчёт (latest: путь относительно <state>/quality) и последняя задача пересчёта."""
    job = S.store.last_job("quality")
    return {"latest": quality.latest(S.settings.state_dir), "job": _job_json(job) if job else None}


@app.post("/ml/models/{version}/activate", dependencies=[Depends(auth)])
async def activate(version: str) -> dict:
    if version not in registry.versions(S.settings.models_dir):
        raise ApiError(404, "model_not_found", "Такой версии модели нет.")
    S.store.set_kv(registry.ACTIVE_KEY, version)
    S.model_version = version            # воркеры перегрузят контекст на ближайшем запросе
    return {"active": version}


@app.get("/ml/reports/{name}", dependencies=[Depends(auth)])
async def get_report(name: str) -> dict:
    r = registry.report(S.settings.reports_dir, name)
    if r is None:
        raise ApiError(404, "report_not_found", "Такого отчёта нет.")
    return r
