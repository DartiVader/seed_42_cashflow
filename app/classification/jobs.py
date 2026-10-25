"""Фоновый запуск классификации после загрузки: своё синхронное соединение, ошибки только в лог."""
import logging
import time
from datetime import date

import psycopg

from app.classification import client
from app.classification.classify_operation import classify_operations_by_session_id
from app.config import get_settings

log = logging.getLogger("backend.classification")


def classify_session(session_id: int, as_of: date | None) -> None:
    started = time.perf_counter()
    settings = get_settings()
    use_llm = settings.classifier_enabled and client.available()
    if settings.classifier_enabled and not use_llm:
        log.warning("classifier unavailable session_id=%s: categories by rules and counterparty only", session_id)
    config = {"use_llm": use_llm, "llm_workers": settings.classifier_workers}
    try:
        # autocommit: connection.transaction() на компанию — настоящий коммит, а не точка сохранения в общей
        # транзакции; обрыв посреди длинной классификации не откатывает уже посчитанные компании
        with psycopg.connect(settings.database_url, autocommit=True) as connection:
            out = classify_operations_by_session_id(session_id, connection, as_of=as_of, config=config)
    except Exception as exc:  # noqa: BLE001 — фоновая задача: загрузка уже принята, падать некуда
        log.error("classification failed session_id=%s error=%s", session_id, type(exc).__name__)
        return
    log.info("classification done session_id=%s operations=%d llm=%s took_ms=%d",
             session_id, len(out), use_llm, (time.perf_counter() - started) * 1000)
