import psycopg

from app.classification.classify_operation import classify_operations_by_session_id
from tests.conftest import TEST_URL, register, upload
from tests.test_imports import COMPANIES, HEADER

# Аренда — каждый месяц 5-го, 5 месяцев подряд; плюс разовая закупка
RENT = "".join(
    f"C044;C044-{index:06d};2026-0{month}-05;50000.00;Списание;0012345678;ООО «Арендодатель»;"
    f"Арендная плата за помещение за {month} месяц;100000.00\n"
    for index, month in enumerate(range(4, 9), start=1))
OPERATIONS = HEADER + RENT + (
    "C044;C044-000010;2026-08-20;3000.00;Списание;0087654321;ООО «Поставщик»;Оплата по счёту 7 за товар;97000.00\n")


def categories_of(db, source_operation_id: str) -> set[str]:
    rows = db.execute(
        "SELECT c.name FROM operations_categories oc JOIN categories c ON c.id = oc.category_id "
        "JOIN operation o ON o.id = oc.operation_id WHERE o.source_operation_id = %s",
        [source_operation_id]).fetchall()
    return {row[0] for row in rows}


def test_upload_creates_session_and_categories(client, db):
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    response = client.post("/api/imports", files={"file": ("ops.csv", OPERATIONS.encode("utf-8-sig"), "text/csv")})
    data = response.json()["data"]
    assert data["accepted"] == 6 and data["classifying"] is True

    session = db.execute("SELECT id, user_id FROM sessions WHERE id = %s", [data["sessionId"]]).fetchone()
    assert session is not None
    assert db.execute("SELECT count(*) FROM operation WHERE session_id = %s", [session[0]]).fetchone()[0] == 6

    # Классификация прошла в фоне после ответа (TestClient выполняет фоновые задачи сразу)
    assert categories_of(db, "C044-000003") == {"Регулярный", "ежемесячно", "Обязательный", "Аренда"}
    assert categories_of(db, "C044-000010") == {"Закупки у поставщиков"}
    # Недостающие категории созданы, по одному разу
    names = [row[0] for row in db.execute("SELECT name FROM categories").fetchall()]
    assert len(names) == len(set(name.lower() for name in names))


def test_reclassification_replaces_links(client, db):
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    session_id = client.post("/api/imports", files={"file": ("ops.csv", OPERATIONS.encode("utf-8-sig"), "text/csv")}
                             ).json()["data"]["sessionId"]
    before = db.execute("SELECT count(*) FROM operations_categories").fetchone()[0]
    with psycopg.connect(TEST_URL) as connection:
        out = classify_operations_by_session_id(session_id, connection)
    assert set(out.columns) == {"operation_id", "is_regular", "cadence", "mandatory", "category"}
    assert db.execute("SELECT count(*) FROM operations_categories").fetchone()[0] == before


def test_as_of_is_start_date(client, db):
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    response = client.post("/api/imports", data={"asOf": "2026-08-01"},
                           files={"file": ("ops.csv", OPERATIONS.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 200
    # До 01.08 операции в расчёт не попали — без категорий; из оставшихся аренда уже не регулярна (2 месяца)
    assert categories_of(db, "C044-000001") == set()
    assert categories_of(db, "C044-000005") == {"Обязательный", "Аренда"}

    bad = client.post("/api/imports", data={"asOf": "01-08"},
                      files={"file": ("ops.csv", OPERATIONS.encode("utf-8-sig"), "text/csv")})
    assert bad.status_code == 400 and bad.json()["listErrors"][0]["field"] == "asOf"


def test_companies_only_upload_skips_classification(client):
    register(client, "a@example.ru")
    data = upload(client, COMPANIES).json()["data"]
    assert data["classifying"] is False


def test_manual_operation_gets_session(client, db):
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    payload = {"companyId": "C044", "operationId": "C044-900001", "date": "2026-09-01", "amount": "1500",
               "direction": "Списание", "counterpartyInn": "", "counterpartyName": "ООО «Связь»",
               "paymentPurpose": "Оплата услуг связи за сентябрь"}
    assert client.post("/api/operations", json=payload).status_code == 201
    row = db.execute("SELECT session_id FROM operation WHERE source_operation_id = 'C044-900001'").fetchone()
    assert row[0] is not None
    assert categories_of(db, "C044-900001") == {"Обязательный", "Связь и интернет"}


LLM_OPERATIONS = HEADER + (
    "C044;C044-000201;2026-09-03;7000.00;Списание;;Сидоров Пётр;Перевод Сидорову П.;100000.00\n"
    "C044;C044-000202;2026-09-04;9000.00;Списание;;Иванов Иван;Перевод Иванову И.;91000.00\n"
)


def test_llm_assigns_category_when_rules_do_not(client, db, monkeypatch):
    calls = []

    def fake_classify(text, qtype, instructions, criteria):
        calls.append({"text": text, "qtype": qtype, "instructions": instructions, "criteria": criteria})
        if "Сидоров" in text:
            return {"type": "choice", "choice": "marketing", "confidence": 0.9}
        return {"type": "choice", "choice": "salary", "confidence": 0.3}  # неуверенно → «Прочее»

    monkeypatch.setattr("app.classification.client.classify", fake_classify)
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    session_id = client.post("/api/imports", files={"file": ("ops.csv", LLM_OPERATIONS.encode("utf-8-sig"), "text/csv")}
                             ).json()["data"]["sessionId"]
    with psycopg.connect(TEST_URL) as connection:
        classify_operations_by_session_id(session_id, connection, config={"use_llm": True, "llm_workers": 2})

    assert categories_of(db, "C044-000201") == {"Реклама"}
    assert categories_of(db, "C044-000202") == {"Прочее"}
    assert len(calls) == 2
    call = next(c for c in calls if "Сидоров" in c["text"])
    assert call["qtype"] == "choice" and call["text"] == "Перевод Сидорову П."
    assert "списание" in call["instructions"] and "Сидоров Пётр" in call["instructions"]
    # Для списания — только категории списаний (и общие), без выручки
    assert "marketing" in call["criteria"] and "revenue_client" not in call["criteria"]
    assert call["criteria"]["marketing"].startswith("Реклама: ")


def test_classifier_down_falls_back_to_rules(monkeypatch):
    import httpx
    from app.classification import client as classifier

    def down(*args, **kwargs):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(classifier.httpx, "get", down)
    assert classifier.available() is False
