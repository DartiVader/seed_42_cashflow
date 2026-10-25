"""Отчёт о качестве модели по компаниям, загруженным администраторами.

Задача job_pool: выгрузка из БД (db.export_admin_dataset) → python -m ml.evaluation.control в подпроцессе →
<state>/quality/<job_id>/report. Готовый отчёт отмечается в <state>/quality/latest.json; бэкенд читает его
через общий том. Хранятся три последних отчёта.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from service.store import Store, now

APP_ROOT = Path(__file__).resolve().parents[1]      # ml/, models/, reports/ — относительные пути control
KEEP_REPORTS = 3


def quality_dir(state_dir: str | Path) -> Path:
    return Path(state_dir) / "quality"


def latest(state_dir: str | Path) -> dict | None:
    path = quality_dir(state_dir) / "latest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fail(st: Store, job_id: str, code: str, message: str) -> None:
    st.update_job(job_id, status="failed", finished_at=now(), error={"code": code, "message": message})


def run_quality_job(db_path: str, job_id: str, state_dir: str, workers: int) -> None:
    from service.db import DatabaseUnavailableError, export_admin_dataset
    st = Store(Path(db_path))
    root = quality_dir(state_dir)
    job_dir = root / job_id
    data_dir, report_dir = job_dir / "data", job_dir / "report"
    st.update_job(job_id, status="running", started_at=now(), stage="export", progress=0.02)
    try:
        companies = export_admin_dataset(data_dir)
    except DatabaseUnavailableError:
        _fail(st, job_id, "db_unavailable", "База данных недоступна.")
        return
    if companies == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        _fail(st, job_id, "no_admin_data", "Нет компаний с операциями, загруженных администратором.")
        return

    st.update_job(job_id, stage="control", progress=0.05)
    cmd = [sys.executable, "-m", "ml.evaluation.control", "--data", str(data_dir), "--out", str(report_dir),
           "--workers", str(workers)]
    with open(job_dir / "control.log", "wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=APP_ROOT)
        while proc.poll() is None:
            time.sleep(5)
            st.update_job(job_id, progress=min(0.95, (st.get_job(job_id)["progress"] or 0) + 0.005))
    shutil.rmtree(data_dir, ignore_errors=True)      # выгрузка с данными компаний больше не нужна
    if proc.returncode != 0 or not (report_dir / "metrics_gaps.csv").exists():
        _fail(st, job_id, "quality_failed", "Отчёт о качестве не посчитался. Подробности — в логе сервиса.")
        return

    pointer = {"job_id": job_id, "finished_at": now(), "companies": companies, "report": f"{job_id}/report"}
    tmp = root / "latest.json.tmp"
    tmp.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, root / "latest.json")
    for old in sorted((p for p in root.iterdir() if p.is_dir() and p.name != job_id),
                      key=lambda p: p.stat().st_mtime)[:-(KEEP_REPORTS - 1) or None]:
        shutil.rmtree(old, ignore_errors=True)
    st.update_job(job_id, status="done", stage="ready", progress=1.0, finished_at=now())
