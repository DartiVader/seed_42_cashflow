"""
mock_marketplace_api.py

Мок OZON + Wildberries + Yandex Market. Один CSV, три API.

Запуск:
    uvicorn mock_marketplace_api:app --host 0.0.0.0 --port 8000
"""
import io
import os
import uuid
import zipfile
from datetime import datetime, timezone

import pandas as pd
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Body, Query
from fastapi.responses import FileResponse, Response


# ════════════════════════════════════════════════════════════════════════════
#  Конфигурация — переопределяется в conftest.py
# ════════════════════════════════════════════════════════════════════════════
CSV_PATH        = "/home/data/synas/nas_backup/home/vitaliy/hakaton/statements/C004.csv"
VALID_CLIENT_ID = "test-client-id"
VALID_API_KEY   = "test-api-key"
VALID_WB_TOKEN  = "test-wb-token"
VALID_YA_TOKEN  = "test-ya-token"

REPORT_DIR     = "generated_reports"
REPORT_STORAGE: dict[str, dict] = {}

os.makedirs(REPORT_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
#  Загрузка данных (вызывается и в тестах через m._load())
# ════════════════════════════════════════════════════════════════════════════
def _load() -> pd.DataFrame:
    if not os.path.exists(CSV_PATH):
        return pd.DataFrame(columns=[
            "company_id", "operation_id", "operation_date", "amount",
            "direction", "counterparty_inn", "counterparty_name",
            "payment_purpose", "balance_eod", "operation_num",
        ])
    df = pd.read_csv(CSV_PATH, sep=";", dtype=str, keep_default_na=False)
    df["operation_date"] = pd.to_datetime(df["operation_date"])
    df["amount"]        = df["amount"].astype(float)
    df["balance_eod"]   = df["balance_eod"].astype(float)
    df["operation_num"] = df["operation_id"].str.extract(r"(\d+)$").astype(int)
    return df


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

    df = _df.copy()
    if date_from: df = df[df["operation_date"] >= pd.to_datetime(date_from[:19])]
    if date_to:   df = df[df["operation_date"] <= pd.to_datetime(date_to[:19])]

    # ── Группируем операции по месяцам ──────────────────────────────────
    df = df.copy()
    df["month"] = df["operation_date"].dt.to_period("M")

    periods = []
    for month_key, group in df.groupby("month"):
        period_begin = month_key.start_time
        period_end   = group["operation_date"].max()
        period_id    = int(period_begin.strftime("%Y%m%d")) * 10_000 + len(group)

        # ── Все маски считаем на group, чтобы индексы совпадали с grp
        #    в details. Раньше они считались на outcome → IndexingError.
        is_income        = group["direction"].str.contains("Поступление", na=False)
        is_outcome       = group["direction"].str.contains("Списание",     na=False)
        purposes_all     = group["payment_purpose"].str.lower()
        counterparty_all = group["counterparty_name"].str.lower()

        commission_mask = is_outcome & purposes_all.str.contains(
            "комисси", na=False
        )
        # «Пополнение расчетной записи» в тестовых данных — это логистика
        # (Система взимания платы), а не «прочие услуги».
        delivery_mask = is_outcome & (
            purposes_all.str.contains(
                r"доставк|провоз|транспорт|экспедиц|перевозк|грузоперевоз"
                r"|расчетн\w*\s*запис|взимани\w*\s*плат",
                na=False,
            )
            | counterparty_all.str.contains(
                r"взимани\w*\s*плат", na=False
            )
        )
        service_mask = is_outcome & ~commission_mask & ~delivery_mask

        orders_amount     = float(group.loc[is_income,       "amount"].sum())
        commission_amount = float(group.loc[commission_mask, "amount"].sum())
        delivery_amount   = float(group.loc[delivery_mask,   "amount"].sum())
        services_amount   = float(group.loc[service_mask,    "amount"].sum())

        first = group.iloc[0]
        begin_balance = (
            first["balance_eod"]
            - first["amount"] * (1 if "Поступление" in first["direction"] else -1)
        )
        end_balance = float(group.iloc[-1]["balance_eod"])

        periods.append({
            "public": {
                "period": {
                    "begin": period_begin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "end":   period_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "id":    period_id,
                },
                "currency_code":                   "RUB",
                "orders_amount":                   round(orders_amount, 2),
                "returns_amount":                  0.0,
                "commission_amount":               round(commission_amount, 2),
                "item_delivery_and_return_amount": round(delivery_amount, 2),
                "services_amount":                 round(services_amount, 2),
            },
            "internal": {
                "group":           group,
                "commission_mask": commission_mask,
                "delivery_mask":   delivery_mask,
                "service_mask":    service_mask,
                "begin_balance":   round(begin_balance, 2),
                "end_balance":     round(end_balance, 2),
            },
        })

    periods.sort(key=lambda p: p["public"]["period"]["begin"])
    total      = len(periods)
    page_count = max(1, (total + page_size - 1) // page_size)
    page_items = periods[(page - 1) * page_size : page * page_size]

    cash_flows = [p["public"] for p in page_items]

    # ── Details — только для ПЕРВОГО периода на странице (как в реальном OZON)
    details = None
    if with_details and page_items:
        item = page_items[0]
        grp  = item["internal"]["group"]

        def _items(mask):
            sub = grp.loc[mask]
            if sub.empty:
                return {"total": 0.0, "items": []}
            by_cp = (sub.groupby("counterparty_name")["amount"]
                        .sum().round(2).to_dict())
            return {
                "total": round(float(sub["amount"].sum()), 2),
                "items": [{"name": k or "—", "price": float(v)}
                          for k, v in by_cp.items()],
            }

        payments = [
            {
                "payment": round(
                    (1 if "Поступление" in r["direction"] else -1) * float(r["amount"]),
                    2,
                ),
                "currency_code": "RUB",
            }
            for _, r in grp.iterrows()
        ]

        details = {
            "period":               item["public"]["period"],
            "payments":             payments,
            "begin_balance_amount": item["internal"]["begin_balance"],
            "delivery": {
                "total":             item["public"]["item_delivery_and_return_amount"],
                "amount":            item["public"]["item_delivery_and_return_amount"],
                "delivery_services": _items(item["internal"]["delivery_mask"]),
            },
            "return": {
                "total":           0.0,
                "amount":          0.0,
                "return_services": {"total": 0.0, "items": []},
            },
            "loan":             0.0,
            "invoice_transfer": 0.0,
            "rfbs": {
                "total":                       0.0,
                "transfer_delivery":           0.0,
                "transfer_delivery_return":    0.0,
                "compensation_delivery_return": 0.0,
                "partial_compensation":        0.0,
                "partial_compensation_return": 0.0,
            },
            "services": _items(item["internal"]["service_mask"]),
            "others":   {"total": 0.0, "items": []},
            "end_balance_amount": item["internal"]["end_balance"],
        }

    return {
        "result": {
            "cash_flows": cash_flows,
            "details":    details,
            "page_count": page_count,
        }
    }


# ── Wildberries: POST /api/finance/v1/sales-reports/list ──────────────────
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
    period    = body.get("period", "weekly")   # "weekly" | "daily"

    if not date_from or not date_to:
        raise HTTPException(400, "dateFrom and dateTo are required")

    df = _df.copy()
    df = df[df["operation_date"] >= pd.to_datetime(date_from)]
    df = df[df["operation_date"] <= pd.to_datetime(date_to)]

    freq = "D" if period == "daily" else "M"
    df   = df.copy()
    df["bucket"] = df["operation_date"].dt.to_period(freq)

    reports = []
    for bucket, grp in df.groupby("bucket"):
        report_id = int(
            bucket.start_time.strftime("%Y%m%d")
        ) * 10_000 + len(reports) + 1

        income  = grp[grp["direction"].str.contains("Поступление")]
        outcome = grp[grp["direction"].str.contains("Списание")]

        purposes         = outcome["payment_purpose"].str.lower()
        counterparty_out = outcome["counterparty_name"].str.lower()

        commission_mask = purposes.str.contains("комисси", na=False)
        # «Пополнение расчетной записи» / «Система взимания платы» —
        # это логистика, а не «прочие услуги». Тот же фикс, что и в OZON.
        delivery_mask = (
            purposes.str.contains(
                r"доставк|логистик|провоз|транспорт|экспедиц|перевозк"
                r"|расчетн\w*\s*запис|взимани\w*\s*плат",
                na=False,
            )
            | counterparty_out.str.contains(r"взимани\w*\s*плат", na=False)
        )
        storage_mask = purposes.str.contains("хранени", na=False)
        penalty_mask = purposes.str.contains("штраф|пеня|неустойк", na=False)
        service_mask = ~commission_mask & ~delivery_mask & ~storage_mask & ~penalty_mask

        bank_payment = (
            float(income["amount"].sum())
            - float(outcome.loc[commission_mask, "amount"].sum())
            - float(outcome.loc[delivery_mask,   "amount"].sum())
            - float(outcome.loc[storage_mask,    "amount"].sum())
            - float(outcome.loc[penalty_mask,    "amount"].sum())
            - float(outcome.loc[service_mask,    "amount"].sum())
        )

        reports.append({
            "reportId":         report_id,
            "dateFrom":         bucket.start_time.strftime("%Y-%m-%d"),
            "dateTo":           bucket.end_time.strftime("%Y-%m-%d"),
            "createDate":       grp["operation_date"].max().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reportType":       "WEEKLY" if period == "weekly" else "DAILY",
            "currency":         "RUB",
            "status":           "DONE",
            "bankPaymentSum":   f"{bank_payment:.2f}",
            "salesCount":       int(len(income)),
            "returnCount":      0,
            "commissionRub":    f"{outcome.loc[commission_mask, 'amount'].sum():.2f}",
            "deliveryRub":      f"{outcome.loc[delivery_mask,   'amount'].sum():.2f}",
            "storageRub":       f"{outcome.loc[storage_mask,    'amount'].sum():.2f}",
            "penaltyRub":       f"{outcome.loc[penalty_mask,    'amount'].sum():.2f}",
            "additionalPaymentRub": "0.00",
        })

    reports.sort(key=lambda r: r["dateFrom"])
    return reports[offset : offset + limit]


# ── Wildberries: POST /api/finance/v1/sales-reports/detailed ──────────────
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

    month_str = str(report_id)[:8]
    year, month = int(month_str[:4]), int(month_str[4:6])
    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end   = month_start + pd.offsets.MonthEnd(0)

    df = _df.copy()
    df = df[(df["operation_date"] >= month_start) & (df["operation_date"] <= month_end)]
    chunk = df.iloc[rrd_id : rrd_id + limit]

    rows = []
    for _, r in chunk.iterrows():
        is_income = "Поступление" in r["direction"]
        rows.append({
            "reportId":          report_id,
            "rrdId":             int(r["operation_num"]),
            "transactionDate":   r["operation_date"].strftime("%Y-%m-%d"),
            "transactionType":   "SALE" if is_income else "SERVICE",
            "supplierOperName":  r["payment_purpose"],
            "amount":            f"{r['amount']:.2f}" if is_income else f"-{r['amount']:.2f}",
            "currency":          "RUB",
            "inn":               r["counterparty_inn"],
            "counterpartyName":  r["counterparty_name"],
            "paymentPurpose":    r["payment_purpose"],
        })

    return rows


# ── Yandex Market: POST /v2/reports/united-netting/generate ────────────────
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

    df = _df.copy()
    df = df[df["operation_date"] >= pd.to_datetime(info["date_from"])]
    df = df[df["operation_date"] <= pd.to_datetime(info["date_to"])]

    transaction_rows = []
    for _, r in df.iterrows():
        is_income = "Поступление" in r["direction"]
        transaction_rows.append({
            "BUSINESS_ID":            info["business_id"],
            "MODEL":                  "FBS",
            "PARTNER_ID":             1,
            "SHOP_NAME":              r["counterparty_name"] or "",
            "INN":                    r["counterparty_inn"] or "",
            "PLACEMENT_CONTRACT":     "",
            "PROMOTION_CONTRACT":     "",
            "TRANSACTION_DATE":       r["operation_date"].strftime("%Y-%m-%d"),
            "TRANSACTION_ID":         r["operation_id"],
            "ORDER_ID":               "",
            "SHOP_ORDER_ID":          "",
            "ORDER_CREATION_DATE":    "",
            "ORDER_DELIVERY_DATE":    "",
            "CLAIM_NUMBER":           "",
            "ORDER_TYPE":             "",
            "SHOP_SKU":               "",
            "ACT_ID":                 "",
            "ACT_DATE":               "",
            "OFFER_OR_SERVICE_NAME":  r["payment_purpose"] or "",
            "COUNT":                  1,
            "TRANSACTION_SUM":        float(r["amount"]) if is_income else -float(r["amount"]),
            "VAT_RATE":               "",
            "VAT_SUM":                0.0,
            "TRANSACTION_TYPE":       "PAYMENT" if is_income else "SERVICE",
            "TRANSACTION_SOURCE":     "MARKETPLACE",
            "PAYMENT_STATUS":         "DONE",
            "BONUS_ACCOUNT_YEAR_MONTH": "",
            "BANK_ORDER_DATE":        "",
            "BANK_ORDER_ID":          "",
            "BANK_SUM":               0.0,
            "COMMENTS":               "",
        })

    transaction_csv = pd.DataFrame(transaction_rows).to_csv(index=False, sep=",").encode("utf-8")
    empty_csv = pd.DataFrame(columns=["BUSINESS_ID", "TRANSACTION_ID"]).to_csv(index=False).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transaction_date.csv",                        transaction_csv)
        z.writestr("netting_report_accruals.csv",                 empty_csv)
        z.writestr("netting_report_returns_and_compensations.csv", empty_csv)
        z.writestr("netting_report_retentions.csv",               empty_csv)
        z.writestr("netting_bonuses.csv",                         empty_csv)
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="report_{report_id}.zip"'},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)