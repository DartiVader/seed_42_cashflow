"""Тесты идут против настоящего PostgreSQL (TEST_DATABASE_URL), ML и LLM подменены httpx.MockTransport.

Поднять базу: docker run -d --name seed42-pg-test -e POSTGRES_USER=seed -e POSTGRES_PASSWORD=seed \
    -e POSTGRES_DB=seed -p 127.0.0.1:55432:5432 postgres:16-alpine
"""
import json
import os
from collections.abc import Callable

import httpx
import psycopg
import pytest

ADMIN_URL = os.getenv("TEST_DATABASE_ADMIN_URL", "postgresql://seed:seed@localhost:55432/seed")
TEST_DB = "seed_backend_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + "/" + TEST_DB

os.environ.update({
    "DATABASE_URL": TEST_URL,
    "JWT_SECRET": "test-secret-not-for-prod",
    "JWT_COOKIE_SECURE": "false",
    "ML_URL": "http://ml.test",
    "ML_INTERNAL_TOKEN": "test-ml-token",
    "LLM_URL": "http://llm.test",
    "LLM_INTERNAL_TOKEN": "test-llm-token",
    "CLASSIFIER_ENABLED": "false",  # тесты не ходят во внешнюю нейросеть; шаг проверяется подменой classify
    "ADMIN_EMAIL": "admin@seed.test",
    "ADMIN_PASSWORD": "admin-password",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.clients.llm import LlmClient  # noqa: E402
from app.clients.ml import MlClient  # noqa: E402
from app.main import app  # noqa: E402

Handler = Callable[[httpx.Request], httpx.Response]


class FakeServices:
    """Поддельные ML и LLM: ответы задаются по (метод, путь), все запросы записываются."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Handler] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, url: str, status: int = 200, body: object = None,
           handler: Handler | None = None) -> None:
        self.routes[(method, url)] = handler or (lambda req: httpx.Response(status, json=body))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, f"{request.url.scheme}://{request.url.host}{request.url.path}")
        if key in self.routes:
            return self.routes[key](request)
        return httpx.Response(404, json={"detail": "Not Found"})

    def bodies(self, path_part: str) -> list[dict]:
        return [json.loads(r.content) for r in self.calls if path_part in r.url.path and r.content]


@pytest.fixture(scope="session")
def database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")


@pytest.fixture(scope="session")
def app_client(database: None):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fake(app_client: TestClient) -> FakeServices:
    services = FakeServices()
    http = httpx.AsyncClient(transport=httpx.MockTransport(services.handle))
    app.state.ml = MlClient(http, "http://ml.test", "test-ml-token")
    app.state.llm = LlmClient(http, "http://llm.test", "test-llm-token")
    return services


@pytest.fixture
def db():
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE marketplace_connection, operations_categories, categories, sessions, operation, "
                     "counterparty, users_company, company "
                     "RESTART IDENTITY CASCADE")
        conn.execute("DELETE FROM users WHERE NOT is_admin")
        yield conn


@pytest.fixture
def client(app_client: TestClient, fake: FakeServices, db) -> TestClient:
    app_client.cookies.clear()
    return app_client


def register(client: TestClient, email: str, password: str = "password123") -> httpx.Response:
    client.cookies.clear()
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str, password: str = "password123") -> httpx.Response:
    client.cookies.clear()
    return client.post("/api/auth/login", json={"email": email, "password": password})


def create_company(client: TestClient, company_id: str = "C044", inn: str = "0012345678",
                   legal_form: str = "ООО", industry: str = "Общепит") -> httpx.Response:
    return client.post("/api/companies", json={"companyId": company_id, "companyName": f"ООО «{company_id}»",
                                               "companyInn": inn, "legalForm": legal_form, "industry": industry})


def upload(client: TestClient, content: str, name: str = "file.csv") -> httpx.Response:
    return client.post("/api/imports", files={"file": (name, content.encode("utf-8-sig"), "text/csv")})
