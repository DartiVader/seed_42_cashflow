"""Классификатор-нейросеть (d1-omni): очередь заданий POST /jobs → ожидание GET /jobs/{id}/wait.

Тот же API, что в client.py Виталия; адрес — из настроек (CLASSIFIER_URL). Вызывается из фонового потока
классификации, поэтому синхронно. Текст назначения в логи не пишется.
"""
import httpx

from app.config import get_settings

SUBMIT_TIMEOUT_S = 10.0
WAIT_TIMEOUT_S = 60.0
HEALTH_TIMEOUT_S = 3.0


def base_url() -> str:
    return get_settings().classifier_url.rstrip("/")


def submit(payload: dict) -> dict:
    r = httpx.post(f"{base_url()}/jobs", json=payload, timeout=SUBMIT_TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def wait_job(job_id: str, timeout: float = WAIT_TIMEOUT_S) -> dict:
    r = httpx.get(f"{base_url()}/jobs/{job_id}/wait", params={"timeout": timeout}, timeout=timeout + 10)
    r.raise_for_status()
    return r.json()


def classify(text: str, qtype: str, instructions: str, criteria) -> dict:
    sub = submit({"op": "classify", "text": text, "qtype": qtype, "instructions": instructions, "criteria": criteria})
    res = wait_job(sub["job_id"])
    if res["status"] != "done":
        raise RuntimeError(f"Ошибка classify: статус {res['status']}")
    return res["result"]


def available() -> bool:
    """Сервис отвечает: иначе шаг нейросети пропускаем, а не ждём таймаут на каждом запросе."""
    try:
        return httpx.get(f"{base_url()}/docs", timeout=HEALTH_TIMEOUT_S).status_code == 200
    except httpx.HTTPError:
        return False
