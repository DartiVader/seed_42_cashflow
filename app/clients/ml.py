"""Клиент ML-сервиса Андрея. Ошибки ML переводятся в ответы фронту по таблице п. 10 задания.

Понимает оба формата ошибок ML: новый шлюз service/ ({code, message}) и прежний hacaton/ ({error, message}).
"""
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.context import request_id_var
from app.responses import ApiError

log = logging.getLogger("backend.ml")

FORECAST_TIMEOUT = httpx.Timeout(15.0, connect=2.0)
ADMIN_TIMEOUT = httpx.Timeout(30.0, connect=2.0)  # activate грузит контекст модели (~5 с и больше)
HEALTH_TIMEOUT = httpx.Timeout(2.0, connect=1.0)

FORECAST_UNAVAILABLE = "Сервис прогноза сейчас недоступен, попробуйте через минуту"
PLAN_FACT_UNAVAILABLE = "Сверка с фактом сейчас недоступна"
DEFAULT_ML_MESSAGE = "Не удалось построить прогноз по этой выписке"
BUSY_MESSAGE = "Сервис прогноза перегружен. Повторите запрос через несколько секунд."
UNKNOWN_COMPANY = "Прогноз для этой компании пока недоступен: её выписки нет в данных сервиса прогноза"
# Ошибки по данным компании: текст ML уже написан для предпринимателя
DATA_ERRORS = {"invalid_statement", "company_closed", "forecast_error",
               "bad_statement", "account_closed", "no_data", "as_of_out_of_range", "not_processed"}


def _ml_error_body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def translate_error(response: httpx.Response, unavailable: str) -> ApiError:
    """Ответ ML с ошибкой → ApiError для фронта. details валидации в лог не пишем."""
    status = response.status_code
    body = _ml_error_body(response)
    code = body.get("code") or body.get("error")
    message = body.get("message") if isinstance(body.get("message"), str) else None
    if status == 429:
        return ApiError(429, message or BUSY_MESSAGE)
    if status >= 500 or status == 401:
        # 401 — не совпал X-Internal-Token: ошибка настройки, предпринимателю это не объяснить
        return ApiError(503, unavailable)
    if code in ("validation_error", "bad_request"):
        return ApiError(400, "Некорректные параметры прогноза")
    if code in DATA_ERRORS:
        # 404 forecast_error («нет данных по компании») — тоже 422: на 404 фронт уходит в демо-режим
        return ApiError(422, message or DEFAULT_ML_MESSAGE)
    if code == "company_not_found":
        # Компания есть у нас в БД, но ML её не знает
        return ApiError(422, UNKNOWN_COMPANY)
    if code == "job_running":
        return ApiError(409, message or "Дообучение уже идёт")
    if status == 404:
        # 404 без кода ошибки ML — нет такого пути (эндпоинта)
        return ApiError(503, unavailable)
    if status in (400, 422):
        return ApiError(422, message or DEFAULT_ML_MESSAGE)
    return ApiError(503, unavailable)


class MlClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, token: str = ""):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict:
        headers = {"X-Request-ID": request_id_var.get()}
        if self.token:
            headers["X-Internal-Token"] = self.token
        return headers

    async def _call(self, method: str, path: str, *, timeout: httpx.Timeout, unavailable: str,
                    json: Any = None, params: dict | None = None, op: str = "") -> httpx.Response:
        try:
            response = await self.http.request(method, self.base_url + path, json=json, params=params,
                                               timeout=timeout, headers=self._headers())
        except httpx.TimeoutException:
            log.warning("ml %s timeout", op)
            raise ApiError(503, unavailable) from None
        except httpx.HTTPError as exc:
            log.warning("ml %s unreachable: %s", op, type(exc).__name__)
            raise ApiError(503, unavailable) from None
        return response

    async def _json(self, method: str, path: str, *, timeout: httpx.Timeout, unavailable: str, op: str,
                    company_id: str | None = None, **kwargs: Any) -> Any:
        response = await self._call(method, path, timeout=timeout, unavailable=unavailable, op=op, **kwargs)
        if response.status_code >= 400:
            log.warning("ml %s company_id=%s ml_status=%d", op, company_id, response.status_code)
            raise translate_error(response, unavailable)
        try:
            return response.json()
        except ValueError:
            log.warning("ml %s company_id=%s bad json", op, company_id)
            raise ApiError(503, unavailable) from None

    async def forecast(self, company_id: str, user_id: int, body: dict) -> dict:
        # Сценарий — в теле того же /forecast: /scenario у нового шлюза нет, hacaton/ принимал оба.
        # user_id — шлюз берёт из БД только операции этого пользователя (компания общая)
        path = f"/ml/companies/{quote(company_id, safe='')}/forecast"
        return await self._json("POST", path, json=body, params={"user_id": user_id}, timeout=FORECAST_TIMEOUT,
                                unavailable=FORECAST_UNAVAILABLE, op="forecast", company_id=company_id)

    async def plan_fact(self, company_id: str, user_id: int, as_of: str, lookback_days: int,
                        opening_balance: float) -> dict:
        path = f"/ml/companies/{quote(company_id, safe='')}/plan-fact"
        # opening_balance — как в прогнозе: без него факт из БД считается от нулевого остатка
        params = {"as_of": as_of, "lookback_days": lookback_days, "opening_balance": opening_balance,
                  "user_id": user_id}
        return await self._json("GET", path, params=params,
                                timeout=FORECAST_TIMEOUT, unavailable=PLAN_FACT_UNAVAILABLE,
                                op="plan_fact", company_id=company_id)

    async def models(self) -> dict | list:
        return await self._json("GET", "/ml/models", timeout=ADMIN_TIMEOUT,
                                unavailable=FORECAST_UNAVAILABLE, op="models")

    async def activate(self, name: str, version: str) -> dict:
        # Шлюз ждёт полную версию в пути (lgbm_net-v2); фронт может прислать name + короткую версию (v2)
        full = version if version.startswith(name + "-") else f"{name}-{version}"
        path = f"/ml/models/{quote(full, safe='')}/activate"
        response = await self._call("POST", path, json={"version": version}, timeout=ADMIN_TIMEOUT,
                                    unavailable=FORECAST_UNAVAILABLE, op="activate")
        if response.status_code == 404:
            raise ApiError(404, "Такой версии модели нет")
        if response.status_code >= 400:
            raise translate_error(response, FORECAST_UNAVAILABLE)
        return response.json()

    async def retrain(self, body: dict) -> dict:
        response = await self._call("POST", "/ml/models/retrain", json=body, timeout=ADMIN_TIMEOUT,
                                    unavailable=FORECAST_UNAVAILABLE, op="retrain")
        if response.status_code == 422:
            message = _ml_error_body(response).get("message")
            raise ApiError(400, message if isinstance(message, str) else "Недопустимые параметры дообучения")
        if response.status_code >= 400:
            raise translate_error(response, FORECAST_UNAVAILABLE)
        return response.json()

    async def quality_run(self) -> dict:
        """Пересчёт отчёта о качестве по компаниям администраторов (фоновая задача шлюза) → {job_id}."""
        return await self._json("POST", "/ml/quality/run", timeout=ADMIN_TIMEOUT,
                                unavailable=FORECAST_UNAVAILABLE, op="quality_run")

    async def quality_status(self) -> dict:
        """{latest, job}: последний готовый отчёт и последняя задача пересчёта."""
        return await self._json("GET", "/ml/quality", timeout=ADMIN_TIMEOUT,
                                unavailable=FORECAST_UNAVAILABLE, op="quality_status")

    async def job(self, job_id: str) -> dict:
        response = await self._call("GET", f"/ml/jobs/{quote(job_id, safe='')}", timeout=ADMIN_TIMEOUT,
                                    unavailable=FORECAST_UNAVAILABLE, op="job")
        if response.status_code == 404:
            raise ApiError(404, "Задача не найдена")
        if response.status_code >= 400:
            raise translate_error(response, FORECAST_UNAVAILABLE)
        return response.json()

    async def health(self) -> bool:
        """Шлюз: /ml/health со status ok; прежний hacaton/: /health."""
        for path in ("/ml/health", "/health"):
            try:
                response = await self.http.get(self.base_url + path, timeout=HEALTH_TIMEOUT)
            except httpx.HTTPError:
                return False
            if response.status_code == 200:
                body = _ml_error_body(response)
                return body.get("status", "ok") == "ok"
        return False
