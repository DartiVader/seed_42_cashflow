"""Отчёты маркетплейсов по API-ключу → операции в формате выписки.

Запросы и маппинг — как в marketplace_client.py Влада (мок OZON + Wildberries + Яндекс Маркет),
только асинхронно на общем httpx-клиенте. Суммы, ИНН и названия не логируются.
"""
import asyncio
import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from app.responses import ApiError

log = logging.getLogger("backend.marketplaces")

TIMEOUT = httpx.Timeout(30.0, connect=3.0)
YANDEX_POLL_ATTEMPTS = 30
YANDEX_POLL_DELAY_S = 1.0
WB_LIST_LIMIT = 1000
WB_DETAIL_LIMIT = 100_000
OZON_PAGE_SIZE = 100

NAMES = {"ozon": "OZON", "wb": "Wildberries", "yandex": "Яндекс Маркет"}
# Префикс номера операции: номер в БД = <company_id>-<префикс><id маркетплейса>
CODES = {"ozon": "OZ", "wb": "WB", "yandex": "YM"}

UNAVAILABLE = "Маркетплейс сейчас недоступен, попробуйте позже"
BAD_KEY = {
    "ozon": "OZON не принял ключ: проверьте Client-Id и Api-Key",
    "wb": "Wildberries не принял токен: проверьте его в личном кабинете продавца",
    "yandex": "Яндекс Маркет не принял токен: проверьте токен и идентификатор кабинета",
}


@dataclass
class MarketplaceOperation:
    external_id: str
    date: date
    amount: Decimal          # > 0, знак задаёт direction
    direction: str           # «Поступление» | «Списание»
    counterparty_inn: str | None
    counterparty_name: str
    payment_purpose: str | None


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _operation(external_id, day: str, signed: Decimal, inn, name, purpose, marketplace: str) -> MarketplaceOperation:
    return MarketplaceOperation(
        external_id=str(external_id),
        date=date.fromisoformat(day[:10]),
        amount=abs(signed),
        direction="Поступление" if signed >= 0 else "Списание",
        counterparty_inn=(inn or "").strip() or None,
        counterparty_name=(name or "").strip() or NAMES[marketplace],
        payment_purpose=(purpose or "").strip() or None,
    )


class MarketplaceClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, marketplace: str, credentials: dict):
        if marketplace not in NAMES:
            raise ApiError(400, "Такого маркетплейса нет: доступны OZON, Wildberries, Яндекс Маркет", "marketplace")
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.marketplace = marketplace
        self.credentials = credentials

    def _headers(self) -> dict:
        if self.marketplace == "ozon":
            return {"Client-Id": self.credentials["client_id"], "Api-Key": self.credentials["api_key"]}
        return {"Authorization": f"Bearer {self.credentials['token']}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = path if path.startswith("http") else self.base_url + path
        try:
            response = await self.http.request(method, url, timeout=TIMEOUT, **kwargs)
        except httpx.HTTPError as exc:
            log.warning("marketplace %s unreachable: %s", self.marketplace, type(exc).__name__)
            raise ApiError(503, UNAVAILABLE) from None
        if response.status_code in (401, 403):
            raise ApiError(400, BAD_KEY[self.marketplace])
        if response.status_code >= 400:
            log.warning("marketplace %s status=%d", self.marketplace, response.status_code)
            raise ApiError(503, UNAVAILABLE)
        return response

    async def check(self) -> None:
        """Пробный запрос за один день: ключ подходит или ApiError с понятным текстом."""
        today = date.today().isoformat()
        if self.marketplace == "ozon":
            await self._ozon_page(today, today, 1, 1)
        elif self.marketplace == "wb":
            await self._request("POST", "/api/finance/v1/sales-reports/list", headers=self._headers(),
                                json={"dateFrom": today, "dateTo": today, "limit": 1, "offset": 0, "period": "weekly"})
        else:
            await self._yandex_generate(today, today)

    async def fetch(self, date_from: date, date_to: date) -> list[MarketplaceOperation]:
        start, end = date_from.isoformat(), date_to.isoformat()
        if self.marketplace == "ozon":
            return await self._fetch_ozon(start, end)
        if self.marketplace == "wb":
            return await self._fetch_wb(start, end)
        return await self._fetch_yandex(start, end)

    # ── OZON: агрегированный отчёт по месяцам (cash-flow-statement) ──────
    async def _ozon_page(self, start: str, end: str, page: int, page_size: int) -> dict:
        response = await self._request(
            "POST", "/v1/finance/cash-flow-statement/list", headers=self._headers(),
            json={"date": {"from": f"{start}T00:00:00.000Z", "to": f"{end}T23:59:59.999Z"},
                  "with_details": False, "page": page, "page_size": page_size})
        return response.json()["result"]

    async def _fetch_ozon(self, start: str, end: str) -> list[MarketplaceOperation]:
        operations, page = [], 1
        while True:
            result = await self._ozon_page(start, end, page, OZON_PAGE_SIZE)
            for flow in result["cash_flows"]:
                # Нетто периода: продажи − комиссии − доставка − услуги. Направление — по знаку нетто
                net = (_money(flow["orders_amount"]) - _money(flow["commission_amount"])
                       - _money(flow["item_delivery_and_return_amount"]) - _money(flow["services_amount"]))
                begin, finish = flow["period"]["begin"][:10], flow["period"]["end"][:10]
                operations.append(_operation(flow["period"]["id"], begin, net, None, "OZON",
                                             f"Расчёт с OZON за период {begin} — {finish}", "ozon"))
            if page >= result["page_count"]:
                return operations
            page += 1

    # ── Wildberries: список отчётов → построчная детализация ─────────────
    async def _fetch_wb(self, start: str, end: str) -> list[MarketplaceOperation]:
        reports, offset = [], 0
        while True:
            response = await self._request(
                "POST", "/api/finance/v1/sales-reports/list", headers=self._headers(),
                json={"dateFrom": start, "dateTo": end, "limit": WB_LIST_LIMIT, "offset": offset, "period": "weekly"})
            page = response.json()
            reports.extend(page)
            if len(page) < WB_LIST_LIMIT:
                break
            offset += WB_LIST_LIMIT

        operations = []
        for report in reports:
            rrd_id = 0
            while True:
                response = await self._request(
                    "POST", "/api/finance/v1/sales-reports/detailed", headers=self._headers(),
                    json={"reportId": report["reportId"], "limit": WB_DETAIL_LIMIT, "rrdId": rrd_id})
                chunk = response.json()
                for item in chunk:
                    operations.append(_operation(
                        f"{report['reportId']}-{item['rrdId']}", item["transactionDate"], _money(item["amount"]),
                        item.get("inn"), item.get("counterpartyName"),
                        item.get("paymentPurpose") or item.get("supplierOperName"), "wb"))
                if len(chunk) < WB_DETAIL_LIMIT:
                    break
                rrd_id = chunk[-1]["rrdId"]
        return operations

    # ── Яндекс Маркет: генерация отчёта → опрос статуса → ZIP с CSV ──────
    async def _yandex_generate(self, start: str, end: str) -> str:
        response = await self._request(
            "POST", "/v2/reports/united-netting/generate", headers=self._headers(),
            params={"format": "CSV", "language": "RU"},
            json={"businessId": self.credentials["business_id"], "dateFrom": start, "dateTo": end})
        return response.json()["result"]["reportId"]

    async def _fetch_yandex(self, start: str, end: str) -> list[MarketplaceOperation]:
        report_id = await self._yandex_generate(start, end)
        file_url = None
        for _ in range(YANDEX_POLL_ATTEMPTS):
            info = (await self._request("GET", f"/v2/reports/info/{report_id}", headers=self._headers())).json()["result"]
            if info["status"] == "DONE":
                file_url = info["file"]
                break
            if info["status"] == "FAILED":
                raise ApiError(503, "Яндекс Маркет не смог сформировать отчёт, попробуйте позже")
            await asyncio.sleep(YANDEX_POLL_DELAY_S)
        if not file_url:
            raise ApiError(503, "Яндекс Маркет не успел сформировать отчёт, попробуйте позже")

        archive = (await self._request("GET", file_url, headers=self._headers())).content
        with zipfile.ZipFile(io.BytesIO(archive)) as z, z.open("transaction_date.csv") as f:
            rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
        return [_operation(row["TRANSACTION_ID"], row["TRANSACTION_DATE"], _money(row["TRANSACTION_SUM"]),
                           row.get("INN"), row.get("SHOP_NAME"),
                           row.get("OFFER_OR_SERVICE_NAME") or row.get("COMMENTS"), "yandex")
                for row in rows]
