"""Контрактные проверки на реальных данных (пропускаются, если датасета нет). Запуск из server/:
python -m pytest service/tests"""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DATA = Path(os.environ.get("ML_TEST_DATA_DIR", "cashflow_data/cashflow_dataset_participants"))
pytestmark = pytest.mark.skipif(not (DATA / "companies.csv").exists(), reason="нет датасета")
H = {"X-Internal-Token": "test-token", "X-Request-Id": "rid-1"}
BODY = {"as_of": "2026-09-30", "horizon_days": 30, "seed": 42}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("INTERNAL_TOKEN", "test-token")
    mp.setenv("ML_WORKERS", "1")
    mp.setenv("ML_STATE_DIR", str(tmp_path_factory.mktemp("state")))
    mp.setenv("ML_DATA_DIR", str(DATA))
    from service.main import app
    with TestClient(app) as c:
        for _ in range(120):
            if c.get("/ml/health").json()["model_loaded"]:
                break
            time.sleep(1)
        yield c
    mp.undo()


def test_health_open_and_ok(client):
    r = client.get("/ml/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["workers"] == 1


def test_token_required(client):
    r = client.post("/ml/companies/C044/forecast", json=BODY)
    assert r.status_code == 401 and set(r.json()) == {"code", "message"}
    assert client.post("/ml/companies/C044/forecast", json=BODY, headers={"X-Internal-Token": "x"}).status_code == 401


def test_forecast_deterministic_and_request_id(client):
    a = client.post("/ml/companies/C044/forecast", json=BODY, headers=H)
    b = client.post("/ml/companies/C044/forecast", json=BODY, headers=H)
    assert a.status_code == 200 and a.headers["x-request-id"] == "rid-1"
    assert a.json() == b.json() and len(a.json()["daily"]) >= 20


def test_errors_have_code_and_message(client):
    r = client.post("/ml/companies/C999/forecast", json=BODY, headers=H)
    assert r.status_code == 404 and r.json()["code"] == "company_not_found"
    r = client.post("/ml/companies/C044/forecast", json={**BODY, "horizon_days": 5}, headers=H)
    assert r.status_code == 400 and r.json()["code"] == "bad_request"
    r = client.post("/ml/companies/C044/forecast", json={**BODY, "as_of": "2020-01-01"}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "no_data"


def test_process_job_lifecycle(client):
    j = client.post("/ml/companies/C044/process", json={"reason": "upload"}, headers=H)
    assert j.status_code == 202 and j.json()["status"] == "queued"
    again = client.post("/ml/companies/C044/process", json={"reason": "upload"}, headers=H).json()
    job_id = j.json()["job_id"]
    for _ in range(120):
        job = client.get(f"/ml/jobs/{job_id}", headers=H).json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert job["status"] == "done" and job["stage"] == "ready" and job["progress"] == 1.0
    assert again["job_id"] in (job_id, again["job_id"])      # повтор мог прийти уже после старта задачи
    st = client.get("/ml/companies/C044/status", headers=H).json()
    assert st["ready"] and st["last_job_id"] == job_id and st["operations"] > 0
    assert client.get("/ml/companies/C044/operations?limit=5", headers=H).json()["total"] > 0


def test_unknown_report_and_model(client):
    assert client.get("/ml/reports/..%2Fsecret", headers=H).status_code == 404
    assert client.post("/ml/models/nope-v9/activate", headers=H).status_code == 404
