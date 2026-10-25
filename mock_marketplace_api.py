"""
mock_marketplace_api.py

Мок OZON + Wildberries + Yandex Market.
Возвращает СТАТИЧЕСКИЕ ответы из папки examples/ — не читает CSV.

Запуск:
    uvicorn mock_marketplace_api:app --host 0.0.0.0 --port 8000
"""
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Body, Query
from fastapi.responses import Response


# ════════════════════════════════════════════════════════════════════════════
#  Конфигурация
# ════════════════════════════════════════════════════════════════════════════
EXAMPLES_DIR    = Path(__file__).parent / "examples"
REPORT_DIR      = "generated_reports"

VALID_CLIENT_ID = "test-client-id"
VALID_API_KEY   = "test-api-key"
VALID_WB_TOKEN  = "test-wb-token"
VALID_YA_TOKEN  = "test-ya-token"

REPORT_STORAGE: dict[str, dict] = {}

os.makedirs(REPORT_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
#  Загрузка статических примеров
# ════════════════════════════════════════════════════════════════════════════
def _load_examples():
    ozon        = json.loads((EXAMPLES_DIR / "ozon_cash_flow.json").read_text(encoding="utf-8"))
    wb_list     = json.loads((EXAMPLES_DIR / "wb_sales_reports.json").read_text(encoding="utf-8"))
    wb_detailed = json.loads((EXAMPLES_DIR / "wb_sales_report_detailed.json").read_text(encoding="utf-8"))
    yandex_csv  = (EXAMPLES_DIR / "yandex_transaction_date.csv").read_text(encoding="utf-8")
    return ozon, wb_list, wb_detailed, yandex_csv


OZON_EXAMPLE, WB_LIST_EXAMPLE, WB_DETAILED_EXAMPLE, YANDEX_CSV_EXAMPLE = _load_examples()


# ════════════════════════════════════════════════════════════════════════════
#  Backward-compat: conftest.py вызывает m._load() и m._df
#  (сервер этих данных больше не использует, но не ломаем импорт)
# ════════════════════════════════════════════════════════════════════════════
CSV_PATH = None


def _load() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "company_id", "operation_id", "operation_date", "amount",
        "direction", "counterparty_inn", "counterparty_name",
        "payment_purpose", "balance_eod", "operation_num",
    ])


_df = _load()


app = FastAPI(title="Mock Marketplace APIs")


# ── OZON: POST /v1/finance/cash-flow-statement/list ─────────────────────
@app.post("/v1/finance/cash-flow-statement/list")
def ozon_cash_flow_statement(
    body: dict = Body(...),
    client_id: str = Header(..., alias="Client-Id"),
    api_key: str = Header(..., alias="Api-Key"),
):
    if client_id != VALID_CLIENT_ID or api_key != VALID_API_KEY:
        raise HTTPException(401, "Unauthorized")

    date_from    = (body.get("date") or {}).get("from")
    date_to      = (body.get("date") or {}).get("to")
    with_details = bool(body.get("with_details", False))
    page         = max(1, int(body.get("page", 1)))
    page_size    = max(1, min(1000, int(body.get("page_size", 1))))

    cash_flows = list(OZON_EXAMPLE["result"]["cash_flows"])

    if date_from:
        from_d = date_from[:10]
        cash_flows = [cf for cf in cash_flows if cf["period"]["end"][:10] >= from_d]
    if date_to:
        to_d = date_to[:10]
        cash_flows = [cf for cf in cash_flows if cf["period"]["begin"][:10] <= to_d]

    total      = len(cash_flows)
    page_count = max(1, (total + page_size - 1) // page_size)
    start      = (page - 1) * page_size
    page_cf    = cash_flows[start : start + page_size]

    details = None
    if with_details and page_cf:
        example_details = OZON_EXAMPLE["result"].get("details")
        if example_details and example_details["period"]["id"] == page_cf[0]["period"]["id"]:
            details = example_details

    return {
        "result": {
            "cash_flows": page_cf,
            "details":    details,
            "page_count": page_count,
        }
    }


# ── Wildberries: POST /api/finance/v1/sales-reports/list ─────────────────
@app.post("/api/finance/v1/sales-reports/list")
def wb_sales_reports_list(
    body: dict = Body(...),
    authorization: str = Header(...),
):
    if authorization != f"Bearer {VALID_WB_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    date_from = body.get("dateFrom")
    date_to   = body.get("dateTo")
    limit     = min(1000, max(1, int(body.get("limit", 1000))))
    offset    = max(0, int(body.get("offset", 0)))

    if not date_from or not date_to:
        raise HTTPException(400, "dateFrom and dateTo are required")

    reports = list(WB_LIST_EXAMPLE)
    reports = [r for r in reports if r["dateTo"]   >= date_from]
    reports = [r for r in reports if r["dateFrom"] <= date_to]

    return reports[offset : offset + limit]


# ── Wildberries: POST /api/finance/v1/sales-reports/detailed ─────────────
@app.post("/api/finance/v1/sales-reports/detailed")
def wb_sales_reports_detailed(
    body: dict = Body(...),
    authorization: str = Header(...),
):
    if authorization != f"Bearer {VALID_WB_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    report_id = body.get("reportId")
    limit     = min(100_000, max(1, int(body.get("limit", 100_000))))
    rrd_id    = max(0, int(body.get("rrdId", 0)))

    if report_id is None:
        raise HTTPException(400, "reportId is required")

    if not WB_DETAILED_EXAMPLE:
        return []

    example_report_id = WB_DETAILED_EXAMPLE[0]["reportId"]
    if report_id != example_report_id:
        return []

    filtered = [item for item in WB_DETAILED_EXAMPLE if item["rrdId"] > rrd_id]
    return filtered[:limit]


# ── Yandex: POST /v2/reports/united-netting/generate ─────────────────────
@app.post("/v2/reports/united-netting/generate")
def yandex_generate_united_netting(
    body: dict = Body(...),
    authorization: str = Header(...),
    format: str = Query("FILE", pattern="^(FILE|CSV|JSON)$"),
    language: str = Query("RU", pattern="^(RU|EN)$"),
):
    if authorization != f"Bearer {VALID_YA_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    business_id = body.get("businessId")
    date_from   = body.get("dateFrom")
    date_to     = body.get("dateTo")
    if not business_id or not date_from or not date_to:
        raise HTTPException(400, "businessId, dateFrom, dateTo are required")

    report_id = str(uuid.uuid4())

    REPORT_STORAGE[report_id] = {
        "status":       "DONE",
        "sub_status":   None,
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "finished_at":  datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "format":       format,
        "language":     language,
        "business_id":  business_id,
        "date_from":    date_from,
        "date_to":      date_to,
    }

    return {
        "status": "OK",
        "result": {
            "reportId": report_id,
            "estimatedGenerationTime": 0,
        },
    }


@app.get("/v2/reports/info/{report_id}")
def yandex_report_info(report_id: str, authorization: str = Header(...)):
    if authorization != f"Bearer {VALID_YA_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    info = REPORT_STORAGE.get(report_id)
    if not info:
        raise HTTPException(404, "Report not found")

    result = {
        "status":                  info["status"],
        "generationRequestedAt":   info["requested_at"],
        "estimatedGenerationTime": 0,
    }
    if info["status"] == "DONE":
        result["generationFinishedAt"] = info["finished_at"]
        result["file"] = f"/v2/reports/download/{report_id}"
    if info["sub_status"]:
        result["subStatus"] = info["sub_status"]

    return {"status": "OK", "result": result}


@app.get("/v2/reports/download/{report_id}")
def yandex_download(report_id: str):
    info = REPORT_STORAGE.get(report_id)
    if not info or info["status"] != "DONE":
        raise HTTPException(404, "Report not ready")

    df = pd.read_csv(io.StringIO(YANDEX_CSV_EXAMPLE), dtype=str, keep_default_na=False)
    df = df[df["TRANSACTION_DATE"] >= info["date_from"]]
    df = df[df["TRANSACTION_DATE"] <= info["date_to"]]
    transaction_csv = df.to_csv(index=False, sep=",").encode("utf-8")

    empty_csv = pd.DataFrame(columns=["BUSINESS_ID", "TRANSACTION_ID"]).to_csv(index=False).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transaction_date.csv",                         transaction_csv)
        z.writestr("netting_report_accruals.csv",                  empty_csv)
        z.writestr("netting_report_returns_and_compensations.csv", empty_csv)
        z.writestr("netting_report_retentions.csv",                empty_csv)
        z.writestr("netting_bonuses.csv",                          empty_csv)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="report_{report_id}.zip"'},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)