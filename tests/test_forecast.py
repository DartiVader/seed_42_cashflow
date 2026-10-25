import logging
from decimal import Decimal

import httpx
import pytest

from tests.conftest import create_company, register, upload
from tests.test_imports import COMPANIES, HEADER, OPERATIONS

ML_FORECAST = "http://ml.test/ml/companies/C044/forecast"
ML_RESPONSE = {
    "company_id": "C044", "as_of": "2026-09-30", "model_version": "lgbm_net-v2", "status": "gap_expected",
    "data_quality": {"history_days": 730, "short_history": False},
    "daily": [{"date": "2026-10-01", "p10": -100.5, "p50": 50.0, "p90": 300.25, "prob_below": 0.4}],
    "events": [{"date": "2026-10-05", "amount": -1000.0, "category": "rent", "source": "regular",
                "confidence": 0.9, "stream_id": "s1"}],
    "gaps": [{"date": "2026-10-05", "probability": 0.7, "shortfall": 900.0, "reasons": ["Аренда"], "actions": []}],
}


@pytest.fixture
def owner(client):
    register(client, "owner@example.ru")
    upload(client, COMPANIES)
    upload(client, OPERATIONS)
    return client


def test_forecast_maps_request_and_returns_ml_as_is(owner, fake):
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    events = [
        {"date": "2026-10-05", "amount": -1000, "category": "rent", "source": "regular", "confidence": 0.9,
         "mandatory": True, "stream_id": "s1", "counterparty_name": "Арендодатель", "label": "Аренда",
         "overdue_from": None},
        {"date": "2026-10-06", "amount": 0, "category": "other", "source": "history", "confidence": 1,
         "stream_id": "s2"},
        {"date": "2026-10-07", "amount": 500, "category": "invoice", "source": "invoice", "confidence": 0.8},
    ]
    response = owner.post("/api/companies/C044/forecast",
                          json={"asOf": "2026-09-30", "horizonDays": 30, "threshold": 1000, "events": events},
                          headers={"X-Request-ID": "req-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["methodName"] == "forecast"
    assert body["data"] == ML_RESPONSE

    sent = fake.bodies("/forecast")[0]
    assert sent["as_of"] == "2026-09-30" and sent["horizon_days"] == 30 and sent["threshold"] == 1000
    assert sent["seed"] == 42 and sent["advice"] is True
    assert sent["opening_balance"] == 8800.0
    assert [e["source"] for e in sent["events"]] == ["manual", "manual", "invoice"]
    assert sent["events"][0] == {"date": "2026-10-05", "amount": -1000, "category": "rent", "source": "manual",
                                 "confidence": 0.9, "mandatory": True, "stream_id": "s1"}
    assert sent["events"][1]["amount"] == 0 and sent["events"][1]["stream_id"] == "s2"
    assert "scenario" not in sent
    assert fake.calls[0].headers["X-Request-ID"] == "req-1"
    assert fake.calls[0].headers["X-Internal-Token"] == "test-ml-token"


def test_operations_from_get_operations_period(owner, fake):
    """В ML уходит история из функции БД: остаток на конец дня — из выписки."""
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    owner.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    operations = fake.bodies("/forecast")[0]["operations"]
    assert [(op["operation_date"], op["balance_eod"]) for op in operations] == [
        ("2024-10-01", 10000.0), ("2024-10-01", 10000.0), ("2024-10-01", 10000.0), ("2024-10-02", 9800.0)]
    assert set(operations[0]) == {"operation_id", "operation_date", "amount", "direction_name", "counterparty_inn",
                                  "counterparty_name", "payment_purpose", "balance_eod", "is_nessery",
                                  "is_regular", "is_cadence", "category_dop"}
    # ИНН — строкой с ведущими нулями
    assert operations[0]["counterparty_inn"] == "0068275202"

    # Операции после даты прогноза в ML не уходят
    owner.post("/api/companies/C044/forecast", json={"asOf": "2024-10-01"})
    assert len(fake.bodies("/forecast")[1]["operations"]) == 3


def test_balance_from_statement_not_recalculated(client, db, fake):
    """Скачок остатка без операции (2-й день: 5000 вместо 9800) — функция отдаёт остаток банка как есть."""
    register(client, "owner@example.ru")
    upload(client, COMPANIES)
    upload(client, HEADER + "C044;C044-000001;2024-10-01;1000.00;Поступление;;Покупатель;Оплата;10000.00\n"
                            "C044;C044-000002;2024-10-02;200.00;Списание;;Поставщик;Оплата;5000.00\n")
    manual = {"companyId": "C044", "operationId": "C044-900001", "date": "2024-10-03", "amount": "100",
              "direction": "Списание", "counterpartyInn": "", "counterpartyName": "ООО «Связь»",
              "paymentPurpose": "Связь"}
    assert client.post("/api/operations", json=manual).status_code == 201
    stored = db.execute("SELECT source_operation_id, balance_eod FROM operation ORDER BY date").fetchall()
    assert [(r[0], r[1]) for r in stored] == [("C044-000001", Decimal("10000.00")), ("C044-000002", Decimal("5000.00")),
                                             ("C044-900001", None)]

    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    operations = fake.bodies("/forecast")[0]["operations"]
    assert [op["balance_eod"] for op in operations] == [10000.0, 5000.0, None]


def test_forecast_uses_only_own_operations(owner, fake):
    """Компания общая: второй пользователь со своей выпиской не видит операций первого."""
    register(owner, "second@example.ru")
    upload(owner, COMPANIES)
    upload(owner, HEADER + "C044;C044-000001;2024-10-01;1000.00;Поступление;;Покупатель;Оплата;10000.00\n")
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    assert owner.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"}).status_code == 200
    assert len(fake.bodies("/forecast")[0]["operations"]) == 1
    user_id = owner.get("/api/me").json()["data"]["id"]
    assert fake.calls[0].url.params["user_id"] == str(user_id)


def test_company_without_statement_opening_zero(client, fake):
    register(client, "owner@example.ru")
    create_company(client, "C044")
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    assert client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"}).status_code == 200
    assert fake.bodies("/forecast")[0]["opening_balance"] == 0.0
    assert fake.bodies("/forecast")[0]["operations"] == []


def test_scenario_goes_in_forecast_body(owner, fake):
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    scenario = {"revenue_multiplier": 0.8, "fixed_cost_multiplier": 1.2, "delay_counterparty": {"cp1": 10},
                "extra_expenses": [{"date": "2026-10-10", "amount": -5000, "category": "other",
                                    "source": "regular", "confidence": 1}]}
    response = owner.post("/api/companies/C044/forecast",
                          json={"asOf": "2026-09-30", "events": [], "scenario": scenario})
    assert response.status_code == 200
    sent = fake.bodies("/forecast")[0]["scenario"]
    assert sent["revenue_multiplier"] == 0.8 and sent["delay_counterparty"] == {"cp1": 10}
    assert sent["extra_expenses"][0]["source"] == "manual"


def test_scenario_null_is_plain_forecast(owner, fake):
    fake.on("POST", ML_FORECAST, body=ML_RESPONSE)
    assert owner.post("/api/companies/C044/forecast",
                      json={"asOf": "2026-09-30", "scenario": None}).status_code == 200


@pytest.mark.parametrize("scenario", [{"revenue_multiplier": 2.0}, {"fixed_cost_multiplier": 0.1},
                                      {"revenue_multiplier": "много"}])
def test_scenario_out_of_range_400_without_ml(owner, fake, scenario):
    response = owner.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30", "scenario": scenario})
    assert response.status_code == 400
    assert response.json()["listErrors"][0]["field"] == "scenario"
    assert fake.calls == []


def test_forecast_request_validation(owner, fake):
    response = owner.post("/api/companies/C044/forecast", json={"horizonDays": 5})
    assert response.status_code == 400
    assert {e["field"] for e in response.json()["listErrors"]} == {"asOf", "horizonDays"}
    assert fake.calls == []


@pytest.mark.parametrize("ml_status, ml_body, status, message", [
    (400, {"error": "invalid_statement", "message": "В выписке нет операций за последние 90 дней"}, 422,
     "В выписке нет операций за последние 90 дней"),
    (404, {"error": "forecast_error", "message": "Нет данных по компании C044 на 30.09.2026"}, 422,
     "Нет данных по компании C044 на 30.09.2026"),
    (422, {"error": "company_closed", "message": "Счёт компании закрыт"}, 422, "Счёт компании закрыт"),
    (422, {"error": "forecast_error", "message": "Горизонт прогноза не содержит рабочих дней"}, 422,
     "Горизонт прогноза не содержит рабочих дней"),
    (422, {"error": "validation_error", "details": [{"loc": ["body", "events", 0, "amount"], "msg": "x"}]}, 400,
     "Некорректные параметры прогноза"),
    (503, {"error": "db_unavailable", "message": "База данных недоступна, попробуйте позже."}, 503,
     "Сервис прогноза сейчас недоступен, попробуйте через минуту"),
    (500, None, 503, "Сервис прогноза сейчас недоступен, попробуйте через минуту"),
    # Новый шлюз service/: {code, message}
    (422, {"code": "no_data", "message": "Нет данных по компании C044 на 01.01.2020"}, 422,
     "Нет данных по компании C044 на 01.01.2020"),
    (422, {"code": "account_closed", "message": "Счёт закрыт"}, 422, "Счёт закрыт"),
    (400, {"code": "bad_request", "message": "Неверный запрос: проверьте поля (horizon_days)."}, 400,
     "Некорректные параметры прогноза"),
    (404, {"code": "company_not_found", "message": "Компания не найдена."}, 422,
     "Прогноз для этой компании пока недоступен: её выписки нет в данных сервиса прогноза"),
    (429, {"code": "busy", "message": "Сервис прогноза перегружен. Повторите запрос через несколько секунд."}, 429,
     "Сервис прогноза перегружен. Повторите запрос через несколько секунд."),
    (401, {"code": "unauthorized", "message": "Неверный внутренний токен."}, 503,
     "Сервис прогноза сейчас недоступен, попробуйте через минуту"),
    (503, {"code": "model_not_loaded", "message": "Сервис прогноза сейчас недоступен."}, 503,
     "Сервис прогноза сейчас недоступен, попробуйте через минуту"),
])
def test_ml_errors_translated(owner, fake, ml_status, ml_body, status, message):
    fake.on("POST", ML_FORECAST, status=ml_status, body=ml_body)
    response = owner.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    assert response.status_code == status
    body = response.json()
    assert body["success"] is False and body["data"] is None
    assert body["listErrors"] == [{"field": None, "message": message}]


@pytest.mark.parametrize("error", [httpx.ReadTimeout("timeout"), httpx.ConnectError("refused")])
def test_ml_timeout_and_unreachable_503(owner, fake, error):
    def raise_error(request):
        raise error
    fake.on("POST", ML_FORECAST, handler=raise_error)
    response = owner.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    assert response.status_code == 503
    assert response.json()["listErrors"][0]["message"] == "Сервис прогноза сейчас недоступен, попробуйте через минуту"


def test_plan_fact_proxy_and_missing_endpoint(owner, fake):
    # Эндпоинта у ML ещё нет: FastAPI отвечает 404 без кода ошибки → фронту 503 (он покажет демо)
    response = owner.get("/api/companies/C044/plan-fact", params={"asOf": "2026-09-30", "lookbackDays": 10})
    assert response.status_code == 503
    request = fake.calls[0]
    assert request.url.params["as_of"] == "2026-09-30" and request.url.params["lookback_days"] == "10"
    assert float(request.url.params["opening_balance"]) == 8800.0

    plan = {"as_of_plan": "2026-09-16", "daily": [], "events": [], "summary": {"missed_in": 0, "missed_out": 0,
                                                                              "max_deviation": None}}
    fake.on("GET", "http://ml.test/ml/companies/C044/plan-fact", body=plan)
    response = owner.get("/api/companies/C044/plan-fact", params={"asOf": "2026-09-30"})
    assert response.status_code == 200 and response.json()["data"] == plan


def test_explain(owner, fake):
    answer = {"text": "Через неделю денег не хватит на аренду.", "source": "llm", "verified": True}
    fake.on("POST", "http://llm.test/explain", body=answer)
    response = owner.post("/api/companies/C044/explain",
                          json={"kind": "summary", "forecast": ML_RESPONSE, "base": None, "question": None})
    assert response.status_code == 200 and response.json()["data"] == answer
    sent = fake.bodies("/explain")[0]
    assert sent == {"kind": "summary", "forecast": ML_RESPONSE, "base": None, "question": None}
    assert fake.calls[-1].headers["X-Internal-Token"] == "test-llm-token"

    assert owner.post("/api/companies/C044/explain", json={"kind": "poem", "forecast": {}}).status_code == 400


def test_explain_llm_down_503(owner, fake):
    def down(request):
        raise httpx.ConnectError("refused")
    fake.on("POST", "http://llm.test/explain", handler=down)
    response = owner.post("/api/companies/C044/explain", json={"kind": "summary", "forecast": ML_RESPONSE})
    assert response.status_code == 503
    assert response.json()["listErrors"][0]["message"] == "Объяснение сейчас недоступно"


def test_logs_have_no_sensitive_data(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    fake.on("POST", ML_FORECAST, status=422, body={"error": "validation_error", "details": [{"msg": "secret-detail"}]})
    register(client, "secret.person@example.ru", "very-secret-pass")
    client.post("/api/auth/login", json={"email": "secret.person@example.ru", "password": "wrong-pass-123"})
    create_company(client, "C044", inn="0098524470")
    upload(client, OPERATIONS)
    client.get("/api/operations", params={"counterpartyInn": "0068275202", "amountFrom": "1000.00"})
    client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30", "events": [
        {"date": "2026-10-05", "amount": -123456.78, "category": "rent", "source": "manual",
         "counterparty_name": "Арендодатель Секретов"}]})

    text = caplog.text
    assert "company_id=C044" in text  # логи пишутся
    for secret in ("secret.person", "very-secret-pass", "wrong-pass-123", "0098524470", "0068275202",
                   "68275202", "123456.78", "1000.00", "10000.00", "ПАО", "Эквайринг", "Арендодатель",
                   "secret-detail"):
        assert secret not in text, secret
