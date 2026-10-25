"""Клиент LLM-сервиса объяснений (llm_service/, POST /explain)."""
import logging

import httpx

from app.context import request_id_var
from app.responses import ApiError

log = logging.getLogger("backend.llm")

EXPLAIN_TIMEOUT = httpx.Timeout(8.0, connect=2.0)
HEALTH_TIMEOUT = httpx.Timeout(2.0, connect=1.0)
UNAVAILABLE = "Объяснение сейчас недоступно"


class LlmClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, token: str = ""):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict:
        headers = {"X-Request-ID": request_id_var.get()}
        if self.token:
            headers["X-Internal-Token"] = self.token
        return headers

    async def explain(self, body: dict) -> dict:
        try:
            response = await self.http.post(self.base_url + "/explain", json=body, timeout=EXPLAIN_TIMEOUT,
                                             headers=self._headers())
        except httpx.HTTPError as exc:
            log.warning("llm explain unreachable: %s", type(exc).__name__)
            raise ApiError(503, UNAVAILABLE) from None
        if response.status_code != 200:
            # 401 — не совпал X-Internal-Token, 400 — сервис не принял тип объяснения
            log.warning("llm explain llm_status=%d", response.status_code)
            raise ApiError(503, UNAVAILABLE)
        try:
            return response.json()
        except ValueError:
            raise ApiError(503, UNAVAILABLE) from None

    async def health(self) -> bool:
        try:
            response = await self.http.get(self.base_url + "/health", timeout=HEALTH_TIMEOUT)
        except httpx.HTTPError:
            return False
        return response.status_code == 200
