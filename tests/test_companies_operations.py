from tests.conftest import create_company, register


def test_company_crud_and_validation(client):
    register(client, "a@example.ru")
    response = create_company(client, inn="0012345678")
    assert response.status_code == 201
    assert response.json()["data"]["companyInn"] == "0012345678"

    response = create_company(client, company_id="C045", inn="12345")
    assert response.status_code == 400
    assert response.json()["listErrors"] == [{"field": "companyInn", "message": "ИНН — 10 цифр для ООО или 12 для ИП"}]
    response = create_company(client, company_id="C045", inn="0012345678")
    assert response.status_code == 409
    response = create_company(client, company_id="C046", inn="0012345679", legal_form="ИП")
    assert response.status_code == 400
    assert response.json()["listErrors"][0]["message"] == "У ИП ИНН из 12 цифр"
    response = create_company(client, company_id="C0123456789")
    assert response.status_code == 400 and response.json()["listErrors"][0]["field"] == "companyId"

    page = client.get("/api/companies", params={"page": 0, "size": 50, "companyName": "", "sortField": "companyInn",
                                                "sortDirection": "desc"}).json()["data"]
    assert page["totalElements"] == 1 and page["totalPages"] == 1 and page["items"][0]["companyId"] == "C044"
    assert client.get("/api/companies", params={"sortField": "password_hash"}).status_code == 400

    response = client.put("/api/companies/C044", json={"companyId": "C044", "companyName": "Новое имя",
                                                       "companyInn": "0012345678", "legalForm": "ООО",
                                                       "industry": "Опт"})
    assert response.status_code == 200
    assert client.get("/api/companies/all").json()["data"][0]["companyName"] == "Новое имя"
    assert client.delete("/api/companies/C044").status_code == 200
    assert client.get("/api/companies/all").json()["data"] == []


def test_foreign_company_is_404(client, fake):
    register(client, "a@example.ru")
    create_company(client, "C044")
    register(client, "b@example.ru")

    assert client.get("/api/companies/all").json()["data"] == []
    response = client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    assert response.status_code == 404
    assert response.json()["listErrors"][0]["message"] == "Компания не найдена"
    assert client.post("/api/companies/C044/explain", json={"kind": "summary", "forecast": {}}).status_code == 404
    assert client.get("/api/companies/C044/plan-fact", params={"asOf": "2026-09-30"}).status_code == 404
    assert client.put("/api/companies/C044", json={"companyId": "C044", "companyName": "x", "companyInn": "0012345678",
                                                   "legalForm": "ООО", "industry": "x"}).status_code == 404
    assert client.delete("/api/companies/C044").status_code == 404
    # Несуществующая — тот же ответ
    assert client.post("/api/companies/C999/forecast", json={"asOf": "2026-09-30"}).status_code == 404
    assert fake.calls == []


def test_operation_crud(client):
    register(client, "a@example.ru")
    create_company(client, "C044")
    payload = {"companyId": "C044", "operationId": "C044-000001", "date": "2026-09-01", "amount": "1500.50",
               "direction": "Поступление", "counterpartyInn": "0068275202", "counterpartyName": "ПАО «Банк»",
               "paymentPurpose": ""}
    response = client.post("/api/operations", json=payload)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["amount"] == 1500.5 and data["counterpartyInn"] == "0068275202" and data["paymentPurpose"] is None

    assert client.post("/api/operations", json=payload).status_code == 409
    bad = client.post("/api/operations", json={**payload, "operationId": "C045-1", "amount": "-1"})
    assert bad.status_code == 400
    assert {e["field"] for e in bad.json()["listErrors"]} == {"amount"}

    page = client.get("/api/operations", params={"companyId": "C044", "amountFrom": "", "dateFrom": "2026-01-01",
                                                 "counterpartyInn": "00682"}).json()["data"]
    assert page["totalElements"] == 1
    assert client.get("/api/operations", params={"sortField": "o.id; drop table users"}).status_code == 400

    op_id = data["id"]
    response = client.put(f"/api/operations/{op_id}", json={**payload, "amount": "99.99", "direction": "Списание"})
    assert response.status_code == 200 and response.json()["data"]["direction"] == "Списание"

    register(client, "b@example.ru")
    assert client.delete(f"/api/operations/{op_id}").status_code == 404
    assert client.get("/api/operations").json()["data"]["totalElements"] == 0
