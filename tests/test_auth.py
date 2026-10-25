from tests.conftest import login, register


def test_register_login_me_logout(client):
    response = register(client, "User@Example.ru")
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True and body["listErrors"] == []
    assert body["data"]["user"] == {"id": body["data"]["user"]["id"], "email": "user@example.ru", "isAdmin": False}
    assert body["data"]["expiresAt"]
    cookie = response.headers["set-cookie"]
    assert "access_token=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie

    response = login(client, "user@example.ru")
    assert response.status_code == 200
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "user@example.ru"

    out = client.post("/api/auth/logout")
    assert out.status_code == 200 and out.json()["data"] is None
    assert "Max-Age=0" in out.headers["set-cookie"]
    assert client.get("/api/me").status_code == 401


def test_without_cookie_401(client):
    response = client.get("/api/me")
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False and body["data"] is None
    assert body["listErrors"][0]["message"]
    assert client.get("/api/companies").status_code == 401
    assert client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"}).status_code == 401


def test_bad_token_401(client):
    client.cookies.set("access_token", "not-a-jwt")
    assert client.get("/api/me").status_code == 401


def test_wrong_password(client):
    register(client, "a@example.ru")
    response = login(client, "a@example.ru", "wrong-password")
    assert response.status_code == 401
    assert response.json()["listErrors"][0]["message"] == "Неверный email или пароль"


def test_register_validation_and_duplicate(client):
    response = register(client, "a@example.ru", "short")
    assert response.status_code == 400
    assert response.json()["listErrors"] == [{"field": "password", "message": "Пароль должен быть от 8 до 72 символов"}]
    response = register(client, "not-an-email", "password123")
    assert response.status_code == 400
    assert response.json()["listErrors"][0]["field"] == "email"
    # Тело запроса (пароль) в ответ не возвращается
    assert "short" not in response.text

    assert register(client, "a@example.ru").status_code == 201
    response = register(client, "A@example.ru")
    assert response.status_code == 409
    assert response.json()["listErrors"][0]["field"] == "email"


def test_admin_created_on_startup(client):
    response = login(client, "admin@seed.test", "admin-password")
    assert response.status_code == 200
    assert response.json()["data"]["user"]["isAdmin"] is True


def test_admin_only(client, fake):
    register(client, "user@example.ru")
    assert client.get("/api/admin/models").status_code == 403

    fake.on("GET", "http://ml.test/ml/models", body={"active_version": "lgbm_net-v2", "versions": [],
                                                    "model_comparison": [], "gap_metrics": []})
    login(client, "admin@seed.test", "admin-password")
    response = client.get("/api/admin/models")
    assert response.status_code == 200
    assert response.json()["data"]["active_version"] == "lgbm_net-v2"

    fake.on("POST", "http://ml.test/ml/models/retrain", status=409,
            body={"error": "job_running", "message": "Дообучение уже идёт"})
    response = client.post("/api/admin/models/retrain", json={})
    assert response.status_code == 409


def test_health(client, fake):
    fake.on("GET", "http://ml.test/ml/health", body={"status": "ok", "model_loaded": True})
    assert client.get("/health").json() == {"status": "ok", "db": True, "ml": True, "llm": False}


def test_request_id_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
