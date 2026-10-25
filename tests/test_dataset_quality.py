import io
import json
import zipfile

import pytest

from app.config import Settings, get_settings
from app.main import app
from tests.conftest import login, register, upload
from tests.test_forecast import ML_FORECAST, ML_RESPONSE
from tests.test_imports import COMPANIES, OPERATIONS


def zipped(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8-sig"))
        archive.writestr("__MACOSX/._companies.csv", b"junk")
        archive.writestr("README.md", "не CSV")
    return buffer.getvalue()


def test_dataset_zip_companies_first(client, db):
    register(client, "a@example.ru")
    # В архиве выписка идёт раньше справочника — сервер всё равно грузит справочник первым
    archive = zipped({"statements/C044.csv": OPERATIONS, "companies.csv": COMPANIES})
    response = client.post("/api/imports/dataset", files=[("files", ("dataset.zip", archive, "application/zip"))])
    assert response.status_code == 200
    data = response.json()["data"]
    assert [f["name"] for f in data["files"]] == ["companies.csv", "statements/C044.csv"]
    assert data["companies"] == 2 and data["operations"] == 4
    assert data["rejected"] == 3  # 1 компания + 2 строки выписки
    assert data["companyIds"] == ["C002", "C044"]
    assert data["failedFiles"] == 0 and data["tookMs"] >= 0
    assert db.execute("SELECT count(*) FROM operation").fetchone()[0] == 4


def test_dataset_several_files_and_bad_file(client):
    register(client, "a@example.ru")
    response = client.post("/api/imports/dataset", files=[
        ("files", ("C044.csv", OPERATIONS.encode("utf-8-sig"), "text/csv")),
        ("files", ("companies.csv", COMPANIES.encode("utf-8-sig"), "text/csv")),
        ("files", ("notes.txt", b"hello", "text/plain")),
        ("files", ("other.csv", "a;b\n1;2\n".encode(), "text/csv")),
    ])
    data = response.json()["data"]
    assert data["operations"] == 4 and data["failedFiles"] == 2
    errors = {f["name"]: f.get("error") for f in data["files"]}
    assert errors["notes.txt"] == "Нужен файл CSV или архив ZIP"
    assert "Не удалось распознать файл" in errors["other.csv"]


def test_single_import_reports_company_ids(client):
    register(client, "a@example.ru")
    response = client.post("/api/imports", files={"file": ("c.csv", COMPANIES.encode("utf-8-sig"), "text/csv")})
    assert response.json()["data"]["companyIds"] == ["C002", "C044"]


def test_trace_passed_to_ml(client, fake):
    register(client, "a@example.ru")
    client.post("/api/imports", files={"file": ("c.csv", COMPANIES.encode("utf-8-sig"), "text/csv")})
    fake.on("POST", ML_FORECAST, body={**ML_RESPONSE, "trace": [{"step": 1, "title": "Загрузили выписку"}]})
    response = client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30", "trace": True})
    assert response.json()["data"]["trace"][0]["title"] == "Загрузили выписку"
    assert fake.bodies("/forecast")[0]["trace"] is True
    client.post("/api/companies/C044/forecast", json={"asOf": "2026-09-30"})
    assert "trace" not in fake.bodies("/forecast")[1]


@pytest.fixture
def reports(tmp_path):
    app.dependency_overrides[get_settings] = lambda: Settings(quality_dir=str(tmp_path / "quality"),
                                                               reports_dir=str(tmp_path / "reports"))
    (tmp_path / "quality").mkdir()
    yield tmp_path / "quality"
    app.dependency_overrides.pop(get_settings, None)


ML_QUALITY_RUN = "http://ml.test/ml/quality/run"


def write_report(root, job_id="j_1"):
    report = root / job_id / "report"
    (report / "figures").mkdir(parents=True)
    (root / "latest.json").write_text(json.dumps(
        {"job_id": job_id, "finished_at": "2026-10-25T10:00:00+00:00", "companies": 12, "report": f"{job_id}/report"}),
        encoding="utf-8")
    return report


def test_quality_without_report(client, reports):
    register(client, "a@example.ru")
    data = client.get("/api/quality").json()["data"]
    assert data == {"available": False, "kind": "admin", "canRun": False, "job": None, "source": None}


def test_quality_report_and_whitelist(client, reports):
    report = write_report(reports)
    (report / "summary.json").write_text(json.dumps({"model_version": "lgbm_net-v2"}), encoding="utf-8")
    (report / "regression.csv").write_text("horizon,mae\n1,100.5\n7,200\n", encoding="utf-8")
    (report / "figures" / "reliability.png").write_bytes(b"\x89PNG fake")
    (reports / "secret.png").write_bytes(b"\x89PNG outside")

    assert client.get("/api/quality").status_code == 401
    register(client, "a@example.ru")
    data = client.get("/api/quality").json()["data"]
    assert data["available"] is True
    assert data["source"] == {"companies": 12, "computedAt": "2026-10-25T10:00:00+00:00"}
    assert data["summary"]["model_version"] == "lgbm_net-v2"
    assert data["tables"]["regression"] == {"columns": ["horizon", "mae"], "rows": [[1.0, 100.5], [7.0, 200.0]]}
    assert data["images"] == ["reliability.png"]

    image = client.get("/api/quality/files/reliability.png")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get("/api/quality/files/secret.png").status_code == 404
    assert client.get("/api/quality/files/..%2Fsecret.png").status_code == 404
    assert client.get("/api/quality/files/summary.json").status_code == 404


def test_quality_pointer_outside_folder_ignored(client, reports):
    (reports / "latest.json").write_text(json.dumps({"report": "../.."}), encoding="utf-8")
    register(client, "a@example.ru")
    assert client.get("/api/quality").json()["data"]["available"] is False


def test_quality_run_admin_only_and_after_admin_upload(client, fake, reports):
    fake.on("POST", ML_QUALITY_RUN, status=202, body={"job_id": "j_2"})
    register(client, "a@example.ru")
    assert client.post("/api/quality/run").status_code == 403
    # Загрузка обычного пользователя отчёт не пересчитывает
    upload(client, COMPANIES)
    upload(client, OPERATIONS)
    assert not [c for c in fake.calls if c.url.path == "/ml/quality/run"]

    login(client, "admin@seed.test", "admin-password")
    assert client.get("/api/quality").json()["data"]["canRun"] is True
    response = client.post("/api/quality/run")
    assert response.status_code == 202 and response.json()["data"] == {"jobId": "j_2"}
    upload(client, COMPANIES.replace("C044", "C045").replace("0098524470", "0098524471").replace(
        "C002;ИП", "C009;ИП").replace("003844671674", "003844671679"))
    upload(client, OPERATIONS.replace("C044", "C045"))
    assert len([c for c in fake.calls if c.url.path == "/ml/quality/run"]) == 2



def test_dataset_report_separate(client, reports):
    control = reports.parent / "reports" / "control"
    (control / "figures").mkdir(parents=True)
    (control / "summary.json").write_text(json.dumps({"model_version": "dataset-model"}), encoding="utf-8")
    (control / "figures" / "examples.png").write_bytes(b"\x89PNG dataset")
    register(client, "a@example.ru")
    # Отчёта по компаниям администратора нет, а по датасету — есть; они не смешиваются
    assert client.get("/api/quality").json()["data"]["available"] is False
    data = client.get("/api/quality", params={"source": "dataset"}).json()["data"]
    assert data["available"] is True and data["kind"] == "dataset"
    assert data["summary"]["model_version"] == "dataset-model" and data["images"] == ["examples.png"]
    assert client.get("/api/quality/files/examples.png", params={"source": "dataset"}).status_code == 200
    assert client.get("/api/quality/files/examples.png").status_code == 404
    assert client.get("/api/quality", params={"source": "other"}).status_code == 400
