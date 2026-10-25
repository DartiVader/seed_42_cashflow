"""Собственные таблицы ML (ml_jobs, ml_categories, ml_streams, ml_kv) в SQLite.

Пока общей PostgreSQL нет, это локальное хранилище на volume; SQLite в режиме WAL безопасно читают и пишут
несколько процессов (gateway и воркеры задач). Схема повторяет таблицы из раздела 5 контракта —
переезд на PostgreSQL меняет только этот модуль. В таблицы Spring сюда не пишем и не читаем.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ml_jobs (
    job_id TEXT PRIMARY KEY, company_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0, stage TEXT, params TEXT,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS ix_jobs_company ON ml_jobs(company_id, kind, status);
CREATE TABLE IF NOT EXISTS ml_categories (
    company_id TEXT NOT NULL, operation_id TEXT NOT NULL, operation_date TEXT NOT NULL, amount REAL NOT NULL,
    category TEXT, category_confidence REAL, category_source TEXT, mandatory INTEGER, regular INTEGER, stream_id TEXT,
    PRIMARY KEY (company_id, operation_id));
CREATE INDEX IF NOT EXISTS ix_cat_date ON ml_categories(company_id, operation_date);
CREATE TABLE IF NOT EXISTS ml_streams (
    company_id TEXT NOT NULL, stream_id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (company_id, stream_id));
CREATE TABLE IF NOT EXISTS ml_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- kv ----
    def get_kv(self, key: str, default: str | None = None) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT value FROM ml_kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_kv(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO ml_kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, value))

    # ---- jobs ----
    def create_job(self, kind: str, company_id: str | None, params: dict | None = None,
                   dedupe: bool = False) -> tuple[str, bool]:
        """(job_id, created). dedupe: если для компании уже есть queued-задача того же вида — вернуть её."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if dedupe:
                r = c.execute("SELECT job_id FROM ml_jobs WHERE company_id IS ? AND kind=? AND status='queued' "
                              "ORDER BY created_at LIMIT 1", (company_id, kind)).fetchone()
                if r:
                    return r["job_id"], False
            job_id = "j_" + uuid.uuid4().hex[:8]
            c.execute("INSERT INTO ml_jobs(job_id,company_id,kind,status,params,created_at) VALUES(?,?,?,?,?,?)",
                      (job_id, company_id, kind, "queued", json.dumps(params or {}), now()))
        return job_id, True

    def update_job(self, job_id: str, **fields) -> None:
        if "error" in fields and fields["error"] is not None:
            fields["error"] = json.dumps(fields["error"], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.conn() as c:
            c.execute(f"UPDATE ml_jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))

    def get_job(self, job_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM ml_jobs WHERE job_id=?", (job_id,)).fetchone()
        return _job(r) if r else None

    def queue_position(self, job_id: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM ml_jobs WHERE status='queued' AND kind IN "
                          "(SELECT kind FROM ml_jobs WHERE job_id=?) AND rowid <= "
                          "(SELECT rowid FROM ml_jobs WHERE job_id=?)", (job_id, job_id)).fetchone()
        return int(r["n"])

    def queue_length(self) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) n FROM ml_jobs WHERE status IN ('queued','running')").fetchone()["n"])

    def last_done_job(self, company_id: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM ml_jobs WHERE company_id=? AND status='done' ORDER BY finished_at DESC LIMIT 1",
                          (company_id,)).fetchone()
        return _job(r) if r else None

    def last_job(self, kind: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM ml_jobs WHERE kind=? ORDER BY created_at DESC LIMIT 1", (kind,)).fetchone()
        return _job(r) if r else None

    def fail_stale_jobs(self) -> None:
        """После рестарта сервиса queued/running-задачи потеряны вместе с процессами."""
        with self.conn() as c:
            c.execute("UPDATE ml_jobs SET status='failed', finished_at=?, error=? WHERE status IN ('queued','running')",
                      (now(), json.dumps({"code": "service_restarted",
                                          "message": "Сервис перезапускался во время обработки. Загрузите выписку ещё раз."},
                                         ensure_ascii=False)))

    # ---- categories / streams ----
    def replace_operations(self, company_id: str, rows: list[tuple], from_date: str | None) -> None:
        """rows: (operation_id, date, amount, category, confidence, source, mandatory, regular, stream_id).
        Ручные категории не затираем."""
        with self.conn() as c:
            manual = {r["operation_id"]: r["category"] for r in c.execute(
                "SELECT operation_id, category FROM ml_categories WHERE company_id=? AND category_source='manual'",
                (company_id,))}
            if from_date:
                c.execute("DELETE FROM ml_categories WHERE company_id=? AND operation_date>=? "
                          "AND category_source!='manual'", (company_id, from_date))
            else:
                c.execute("DELETE FROM ml_categories WHERE company_id=? AND category_source!='manual'", (company_id,))
            c.executemany(
                "INSERT OR IGNORE INTO ml_categories(company_id,operation_id,operation_date,amount,category,"
                "category_confidence,category_source,mandatory,regular,stream_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(company_id, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows
                 if r[0] not in manual])

    def replace_streams(self, company_id: str, streams: list[dict]) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM ml_streams WHERE company_id=?", (company_id,))
            c.executemany("INSERT INTO ml_streams(company_id,stream_id,body) VALUES(?,?,?)",
                          [(company_id, s["stream_id"], json.dumps(s, ensure_ascii=False)) for s in streams])

    def streams(self, company_id: str) -> list[dict]:
        with self.conn() as c:
            return [json.loads(r["body"]) for r in c.execute(
                "SELECT body FROM ml_streams WHERE company_id=? ORDER BY stream_id", (company_id,))]

    def operations(self, company_id: str, date_from: str | None, date_to: str | None,
                   limit: int, offset: int) -> tuple[int, list[dict]]:
        where, args = "company_id=?", [company_id]
        if date_from:
            where += " AND operation_date>=?"; args.append(date_from)
        if date_to:
            where += " AND operation_date<=?"; args.append(date_to)
        with self.conn() as c:
            total = c.execute(f"SELECT COUNT(*) n FROM ml_categories WHERE {where}", args).fetchone()["n"]
            rows = c.execute(f"SELECT * FROM ml_categories WHERE {where} ORDER BY operation_date, operation_id "
                             "LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return int(total), [dict(r) for r in rows]

    def count_operations(self, company_id: str) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) n FROM ml_categories WHERE company_id=?", (company_id,)).fetchone()["n"])

    def data_until(self, company_id: str) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT MAX(operation_date) d FROM ml_categories WHERE company_id=?", (company_id,)).fetchone()
        return r["d"]

    def set_manual_category(self, company_id: str, operation_id: str, category: str) -> bool:
        with self.conn() as c:
            cur = c.execute("UPDATE ml_categories SET category=?, category_confidence=1.0, category_source='manual' "
                            "WHERE company_id=? AND operation_id=?", (category, company_id, operation_id))
            return cur.rowcount > 0


def _job(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["error"] = json.loads(d["error"]) if d["error"] else None
    d["params"] = json.loads(d["params"]) if d["params"] else {}
    return d
