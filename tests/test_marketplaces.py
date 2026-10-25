"""Интеграция с маркетплейсами против мока Влада (tests/fixtures/mock_marketplace_api.py) в том же процессе."""
import importlib
from decimal import Decimal

import httpx
import pytest

from app.main import app
from tests.conftest import register, upload
from tests.test_imports import COMPANIES

HEADER = ("company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;"
          "payment_purpose;balance_eod\n")
# Август: продажи 300 000 − комиссия 20 000 − провоз 5 000 → +275 000.
# Сентябрь: продажи 305 000 − прочее 400 000 → −95 000 (нетто отрицательное — это списание)
STATEMENT = HEADER + (
    "C044;C044-000001;2026-08-03;300000.00;Поступление;0012345678;ООО «Клиент А»;Оплата по счёту 12;300000.00\n"
    "C044;C044-000002;2026-08-10;20000.00;Списание;0011111111;OZON;Комиссия за продажи;280000.00\n"
    "C044;C044-000003;2026-08-15;5000.00;Списание;;Система взимания платы;Провоз по дорогам;275000.00\n"
    "C044;C044-000004;2026-09-07;305000.00;Поступление;0012345678;ООО «Клиент А»;Оплата по счёту 21;580000.00\n"
    "C044;C044-000005;2026-09-12;400000.00;Списание;0087654321;ООО «Поставщик»;Оборудование;180000.00\n"
)
PERIOD = {"dateFrom": "2026-08-01", "dateTo": "2026-09-30"}
OZON = {"companyId": "C044", "marketplace": "ozon", "clientId": "test-client-id", "apiKey": "test-api-key"}
WB = {"companyId": "C044", "marketplace": "wb", "token": "test-wb-token"}
YANDEX = {"companyId": "C044", "marketplace": "yandex", "token": "test-ya-token", "businessId": "1"}


@pytest.fixture
def mock(app_client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # мок создаёт generated_reports/ в текущей папке
    statement = tmp_path / "C044.csv"
    statement.write_text(STATEMENT, encoding="utf-8")
    module = importlib.import_module("tests.fixtures.mock_marketplace_api")
    module.CSV_PATH = str(statement)
    module._df = module._load()
    previous = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app))
    yield module
    app.state.http = previous


@pytest.fixture
def owner(client, mock):
    register(client, "owner@example.ru")
    upload(client, COMPANIES)
    return client


def operations(db, prefix: str) -> list[tuple]:
    return db.execute(
        "SELECT o.source_operation_id, o.date::text, o.amount, d.name, o.session_id FROM operation o "
        "JOIN direction d ON d.id = o.direction_id WHERE o.source_operation_id LIKE %s ORDER BY o.date",
        [prefix + "%"]).fetchall()


def test_wrong_key_is_rejected_and_not_saved(owner, db):
    response = owner.post("/api/marketplaces", json={**OZON, "apiKey": "wrong"})
    assert response.status_code == 400
    assert response.json()["listErrors"][0]["message"] == "OZON не принял ключ: проверьте Client-Id и Api-Key"
    assert db.execute("SELECT count(*) FROM marketplace_connection").fetchone()[0] == 0

    missing = owner.post("/api/marketplaces", json={"companyId": "C044", "marketplace": "yandex", "token": "x"})
    assert missing.status_code == 400 and missing.json()["listErrors"][0]["field"] == "businessId"


def test_connect_list_and_key_is_masked(owner):
    response = owner.post("/api/marketplaces", json=OZON)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["marketplaceName"] == "OZON" and data["keyMasked"] == "•••• -key"
    assert "test-api-key" not in response.text

    listed = owner.get("/api/marketplaces").json()["data"]
    assert [c["marketplace"] for c in listed] == ["ozon"] and "test-api-key" not in str(listed)
    assert owner.post("/api/marketplaces", json=OZON).status_code == 409


def test_ozon_sync_monthly_net_with_sign(owner, db):
    connection_id = owner.post("/api/marketplaces", json=OZON).json()["data"]["id"]
    response = owner.post(f"/api/marketplaces/{connection_id}/sync", json=PERIOD)
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["total"], data["accepted"], data["skipped"], data["rejected"]) == (2, 2, 0, 0)

    rows = operations(db, "C044-OZ")
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("2026-08-01", Decimal("275000.00"), "Поступление"),
        ("2026-09-01", Decimal("95000.00"), "Списание"),
    ]
    assert {r[4] for r in rows} == {data["sessionId"]}
    # Категории посчитаны по сессии загрузки
    assert db.execute("SELECT count(*) FROM operations_categories oc JOIN operation o ON o.id = oc.operation_id "
                      "WHERE o.session_id = %s", [data["sessionId"]]).fetchone()[0] > 0

    # Повторная загрузка того же периода — только пропуски
    again = owner.post(f"/api/marketplaces/{connection_id}/sync", json=PERIOD).json()["data"]
    assert (again["accepted"], again["skipped"]) == (0, 2)
    last = owner.get("/api/marketplaces").json()["data"][0]
    assert last["lastSyncAt"] and last["lastResult"]["skipped"] == 2


def test_wb_and_yandex_sync_per_operation(owner, db):
    wb_id = owner.post("/api/marketplaces", json=WB).json()["data"]["id"]
    wb = owner.post(f"/api/marketplaces/{wb_id}/sync", json=PERIOD).json()["data"]
    assert (wb["total"], wb["accepted"]) == (5, 5)
    rows = operations(db, "C044-WB")
    assert len(rows) == 5 and all(len(r[0]) <= 20 for r in rows)
    assert sum(r[2] for r in rows if r[3] == "Списание") == Decimal("425000.00")

    ya_id = owner.post("/api/marketplaces", json=YANDEX).json()["data"]["id"]
    ya = owner.post(f"/api/marketplaces/{ya_id}/sync", json=PERIOD).json()["data"]
    assert (ya["total"], ya["accepted"]) == (5, 5)
    # ИНН — строкой с ведущими нулями; без ИНН — по названию контрагента
    inns = {r[0] for r in db.execute(
        "SELECT cp.inn FROM operation o JOIN counterparty cp ON cp.id = o.counterparty_id "
        "WHERE o.source_operation_id LIKE 'C044-YM%'").fetchall()}
    assert {"0012345678", "0011111111", "0087654321", None} == inns


def test_other_user_cannot_use_connection(owner, client):
    connection_id = owner.post("/api/marketplaces", json=OZON).json()["data"]["id"]
    register(client, "other@example.ru")
    assert client.get("/api/marketplaces").json()["data"] == []
    assert client.post(f"/api/marketplaces/{connection_id}/sync", json=PERIOD).status_code == 404
    assert client.delete(f"/api/marketplaces/{connection_id}").status_code == 404
    assert client.post("/api/marketplaces", json=OZON).status_code == 404


def test_bad_period(owner):
    connection_id = owner.post("/api/marketplaces", json=OZON).json()["data"]["id"]
    response = owner.post(f"/api/marketplaces/{connection_id}/sync",
                          json={"dateFrom": "2026-09-30", "dateTo": "2026-08-01"})
    assert response.status_code == 400 and response.json()["listErrors"][0]["field"] == "dateTo"


def test_marketplace_down_is_503(owner, mock):
    connection_id = owner.post("/api/marketplaces", json=OZON).json()["data"]["id"]

    def down(request):
        raise httpx.ConnectError("refused")
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    response = owner.post(f"/api/marketplaces/{connection_id}/sync", json=PERIOD)
    assert response.status_code == 503
    assert response.json()["listErrors"][0]["message"] == "Маркетплейс сейчас недоступен, попробуйте позже"
