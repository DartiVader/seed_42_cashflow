from decimal import Decimal

from tests.conftest import login, register, upload

COMPANIES = (
    "company_id;company_name;company_inn;legal_form;industry;first_operation_date;last_operation_date;operations_count\n"
    "C044;ООО «Кофейня»;0098524470;ООО;Общепит;2024-10-01;2026-09-30;5\n"
    "C002;ИП Предприниматель;003844671674;ИП;Грузоперевозки;2024-10-01;2026-09-30;0\n"
    "C003;ООО «Плохая»;123;ЗАО;Опт;2024-10-01;2026-09-30;0\n"
)
HEADER = "company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
# Первый день: поступления 1000 + 500, списание 300, остаток на конец дня 10 000 → на начало 8 800
OPERATIONS = HEADER + (
    "C044;C044-000001;2024-10-01;1000.00;Поступление;0068275202;ПАО «Банк»;Эквайринг; комиссия 1%;10000.00\n"
    "C044;C044-000002;2024-10-01;500.00;Поступление;;Покупатель без ИНН;Оплата;10000.00\n"
    "C044;C044-000003;2024-10-01;300.00;Списание;0068275202;ПАО «Банк»;Комиссия;10000.00\n"
    "C044;C044-000004;2024-10-02;200.00;Списание;68275202;ПАО «Банк»;Excel съел нули в ИНН;9800.00\n"
    "C044;C044-000004;2024-10-02;200.00;Списание;0068275202;ПАО «Банк»;Дубль внутри файла;9800.00\n"
    "C044;C044-000005;2024-10-02;-5;Списание;0068275202;ПАО «Банк»;Отрицательная сумма;9800.00\n"
    "C999;C999-000001;2024-10-02;5.00;Списание;0068275202;ПАО «Банк»;Чужая компания;9800.00\n"
)


def test_import_companies_then_operations(client, db):
    register(client, "a@example.ru")
    report = upload(client, COMPANIES).json()["data"]
    assert report["fileType"] == "COMPANIES"
    assert (report["total"], report["accepted"], report["rejected"]) == (3, 2, 1)
    assert report["errors"][0]["lineNumber"] == 4

    row = db.execute("SELECT company_inn FROM company WHERE company_id = 'C044'").fetchone()
    assert row[0] == "0098524470"
    assert db.execute("SELECT count(*) FROM users_company WHERE company_id = 'C044'").fetchone()[0] == 1

    report = upload(client, OPERATIONS).json()["data"]
    assert report["fileType"] == "OPERATIONS"
    assert report["total"] == 7
    assert report["accepted"] == 4
    assert report["skipped"] == 1
    assert report["rejected"] == 2
    assert [e["lineNumber"] for e in report["errors"]] == [7, 8]

    # ИНН — строкой с ведущими нулями, в том числе восстановленный после Excel
    inns = {r[0] for r in db.execute("SELECT inn FROM counterparty WHERE inn IS NOT NULL").fetchall()}
    assert inns == {"0068275202"}
    purpose = db.execute("SELECT payment_purpose FROM operation WHERE source_operation_id = 'C044-000001'").fetchone()
    assert purpose[0] == "Эквайринг; комиссия 1%"
    # opening_balance = balance_eod самой ранней даты + списания − поступления всех её операций
    balance = db.execute("SELECT opening_balance FROM company WHERE company_id = 'C044'").fetchone()[0]
    assert balance == Decimal("8800.00")

    # Повторная загрузка: всё — дубли, остаток не меняется; пустой остаток операции дописывается из выписки
    db.execute("UPDATE operation SET balance_eod = NULL WHERE source_operation_id = 'C044-000004'")
    db.commit()
    report = upload(client, OPERATIONS).json()["data"]
    assert db.execute("SELECT balance_eod FROM operation WHERE source_operation_id = 'C044-000004'"
                      ).fetchone()[0] == Decimal("9800.00")
    assert (report["accepted"], report["skipped"]) == (0, 5)
    assert db.execute("SELECT opening_balance FROM company WHERE company_id = 'C044'").fetchone()[0] == Decimal("8800.00")

    # Операции видны в списке своему пользователю
    page = client.get("/api/operations", params={"companyId": "C044"}).json()["data"]
    assert page["totalElements"] == 4


def test_two_users_share_company_with_own_operations(client, db):
    register(client, "a@example.ru")
    upload(client, COMPANIES)
    upload(client, OPERATIONS)
    register(client, "b@example.ru")
    assert client.get("/api/companies/all").json()["data"] == []
    # Компания общая: второй пользователь привязывается к ней, а карточку, которой пользуется другой, не меняет
    report = upload(client, COMPANIES.replace("ООО «Кофейня»", "Чужое имя")).json()["data"]
    assert (report["accepted"], report["rejected"]) == (2, 1)
    assert db.execute("SELECT company_name FROM company WHERE company_id = 'C044'").fetchone()[0] == "ООО «Кофейня»"
    assert db.execute("SELECT count(*) FROM company").fetchone()[0] == 2
    assert [c["companyId"] for c in client.get("/api/companies/all").json()["data"]] == ["C002", "C044"]

    # Те же номера операций у другого пользователя — его собственные данные, не повторы
    report = upload(client, OPERATIONS).json()["data"]
    assert (report["accepted"], report["skipped"]) == (4, 1)
    assert client.get("/api/operations").json()["data"]["totalElements"] == 4
    users = db.execute("SELECT user_id, count(*) FROM operation GROUP BY user_id ORDER BY user_id").fetchall()
    assert [n for _, n in users] == [4, 4]

    # Удаление компании убирает только данные пользователя; компания остаётся у первого
    assert client.delete("/api/companies/C044").status_code == 200
    assert db.execute("SELECT count(*) FROM operation WHERE company_id = 'C044'").fetchone()[0] == 4
    login(client, "a@example.ru")
    assert client.get("/api/operations").json()["data"]["totalElements"] == 4


def test_operations_need_company_in_directory(client):
    register(client, "a@example.ru")
    report = upload(client, OPERATIONS).json()["data"]
    assert report["accepted"] == 0
    assert any("сначала загрузите справочник компаний" in e["message"] for e in report["errors"])


def test_import_unknown_header(client):
    register(client, "a@example.ru")
    response = upload(client, "a,b,c\n1,2,3\n")
    assert response.status_code == 400
    assert "Не удалось распознать файл" in response.json()["listErrors"][0]["message"]
    response = client.post("/api/imports")
    assert response.status_code == 400
    assert response.json()["listErrors"] == [{"field": "file", "message": "Выберите файл для загрузки"}]


def test_delimiter_detected_from_header(client, db):
    """Запятая, табуляция, «|»: разделитель берётся из заголовка; кавычки защищают разделитель в значении."""
    register(client, "a@example.ru")
    companies = COMPANIES.replace(";", ",").replace("ООО «Кофейня»", '"ООО «Кофейня», филиал"')
    report = upload(client, companies).json()["data"]
    assert (report["fileType"], report["accepted"], report["rejected"]) == ("COMPANIES", 2, 1)
    name = db.execute("SELECT company_name FROM company WHERE company_id = 'C044'").fetchone()[0]
    assert name == "ООО «Кофейня», филиал"

    comma = HEADER.replace(";", ",") + (
        'C044,C044-000001,2024-10-01,1000.00,Поступление,0068275202,ПАО «Банк»,"Оплата по счёту 7, НДС нет",10000.00\n'
        "C044,C044-000002,2024-10-01,500.00,Поступление,,Покупатель,Оплата без кавычек, с запятой,10500.00\n")
    report = upload(client, comma).json()["data"]
    assert (report["fileType"], report["accepted"], report["rejected"]) == ("OPERATIONS", 2, 0)
    purposes = dict(db.execute("SELECT source_operation_id, payment_purpose FROM operation").fetchall())
    assert purposes == {"C044-000001": "Оплата по счёту 7, НДС нет", "C044-000002": "Оплата без кавычек, с запятой"}

    for delimiter, number in (("\t", 3), ("|", 4)):
        text = HEADER.replace(";", delimiter) + delimiter.join(
            ["C044", f"C044-00000{number}", "2024-10-02", "10.00", "Списание", "", "Банк", "Комиссия", "10490.00"]) + "\n"
        report = upload(client, text).json()["data"]
        assert (report["fileType"], report["accepted"]) == ("OPERATIONS", 1), delimiter
