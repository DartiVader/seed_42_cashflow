"""Операции компании из PostgreSQL (та же БД, что у бэкенда) → выписка в формате датасета для forecast(ops=…).

Данные берутся функцией БД get_operations_period(company_id, start, end): операции за период и остаток на конец
дня из выписки банка (operation.balance_eod). У ручных операций и операций маркетплейсов остатка нет (NULL) —
досчитываем: последний остаток банка + операции после него. Признаки категорий из функции (is_nessery, is_regular,
…) модель не использует — категории и регулярные платежи она считает сама. Сервис только читает БД.
Без DATABASE_URL — прежний режим: операции из CSV-датасета контекста.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger("ml.db")

# Начало истории: остаток на эту дату = opening_balance + операции до неё, раньше любой выписки — вся история
HISTORY_START = date(2000, 1, 1)
CONNECT_TIMEOUT_S = 5

# В БД часть отраслей записана короче, чем в справочнике модели (meta.json) — как в прежнем hacaton/db.py
INDUSTRY_ALIASES = {
    "Общепит": "Общепит (кофейня, кафе)",
    "IT-услуги": "IT-услуги и разработка",
    "Опт": "Оптовая торговля",
}

STATEMENT_COLUMNS = ["company_id", "operation_id", "operation_date", "amount", "direction",
                     "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod"]


class DatabaseUnavailableError(Exception):
    """БД недоступна. Детали (DSN, текст драйвера) наружу не отдаём."""


def db_enabled() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _connect():
    import psycopg
    try:
        return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=CONNECT_TIMEOUT_S)
    except psycopg.Error:
        raise DatabaseUnavailableError() from None


def company_exists(company_id: str) -> bool:
    import psycopg
    try:
        with _connect() as conn:
            return conn.execute("SELECT 1 FROM company WHERE company_id = %s", [company_id]).fetchone() is not None
    except psycopg.Error:
        raise DatabaseUnavailableError() from None


def fetch_statement(company_id: str, end: date, user_id: int | None = None) -> tuple[pd.DataFrame, str | None]:
    """Выписка компании по дату end включительно (get_operations_period) и её отрасль из company.

    Компания общая для пользователей: с user_id — только его операции (operation.user_id).
    """
    import psycopg
    try:
        with _connect() as conn:
            # MATERIALIZED: функция считается отдельно, потом фильтр по пользователю — иначе Postgres встраивает
            # её тело в запрос и на сотнях тысяч операций выбирает план на минуты
            sql = ("WITH p AS MATERIALIZED (SELECT * FROM get_operations_period(%s, %s, %s)) "
                   "SELECT p.operation_id, p.operation_date, p.amount, p.direction_name, p.counterparty_inn, "
                   "p.counterparty_name, p.payment_purpose, p.balance_eod FROM p")
            params: list = [company_id, HISTORY_START, end]
            if user_id is not None:
                sql += " JOIN operation o ON o.id = p.operation_id WHERE o.user_id = %s"
                params.append(user_id)
            sql += " ORDER BY p.operation_date, p.operation_id"
            rows = conn.execute(sql, params).fetchall()
            company = conn.execute("SELECT industry, opening_balance FROM company WHERE company_id = %s",
                                   [company_id]).fetchone()
    except psycopg.Error:
        raise DatabaseUnavailableError() from None

    industry = company[0] if company else None
    opening = float(company[1]) if company and company[1] is not None else 0.0
    industry = INDUSTRY_ALIASES.get(industry, industry)
    df = pd.DataFrame(rows, columns=["operation_id", "operation_date", "amount", "direction", "counterparty_inn",
                                     "counterparty_name", "payment_purpose", "balance_eod"])
    if df.empty:
        return pd.DataFrame(columns=STATEMENT_COLUMNS), industry

    df["company_id"] = company_id
    df["operation_id"] = df["operation_id"].astype(str)
    df["operation_date"] = pd.to_datetime(df["operation_date"])
    df["amount"] = df["amount"].astype(float)              # numeric приходит как Decimal
    df["counterparty_inn"] = df["counterparty_inn"].astype("string")  # ИНН строкой: нули в начале важны
    df["payment_purpose"] = df["payment_purpose"].fillna("")
    if df["balance_eod"].isna().any():
        df["balance_eod"] = fill_balance(df, opening)
    df["balance_eod"] = df["balance_eod"].astype(float)
    log.info("company_id=%s user_id=%s: операций из БД %d", company_id, user_id, len(df))
    return df[STATEMENT_COLUMNS], industry


def fill_balance(df: pd.DataFrame, opening: float) -> pd.Series:
    """Остаток на конец дня там, где его нет: последний остаток банка + оборот после него.

    До первого остатка банка — от него назад; остатков банка нет совсем — opening_balance + оборот (компания без
    выписки). Дни с остатком банка не меняются.
    """
    sign = df["direction"].map({"Поступление": 1.0, "Списание": -1.0}).fillna(0.0)
    total = (df["amount"] * sign).groupby(df["operation_date"]).sum().cumsum()
    bank = df["balance_eod"].astype(float).groupby(df["operation_date"]).last()   # last() пропускает NULL
    shift = (bank - total).ffill().bfill().fillna(opening)
    return df["operation_date"].map(total + shift)


# ---------------------------------------------------------------- данные для отчёта о качестве

COMPANY_COLUMNS = ["company_id", "company_name", "company_inn", "legal_form", "industry",
                   "first_operation_date", "last_operation_date", "operations_count"]

# Компании администраторов: связь из users_company; если компания у нескольких админов — данные одного (min id),
# чтобы одна выписка не попала в отчёт дважды
ADMIN_COMPANIES_SQL = """
WITH admin_company AS (
    SELECT uc.company_id, min(uc.user_id) AS user_id
    FROM users_company uc JOIN users u ON u.id = uc.user_id
    WHERE u.is_admin
    GROUP BY uc.company_id
)
"""


def export_admin_dataset(dest: Path) -> int:
    """Компании, загруженные администраторами, и их операции → dest/companies.csv и dest/all_operations.csv
    (формат датасета кейса для ml.evaluation.control). → число компаний с операциями."""
    import psycopg
    try:
        with _connect() as conn:
            companies = conn.execute(ADMIN_COMPANIES_SQL + """
                SELECT c.company_id, c.company_name, c.company_inn, lf.code, c.industry,
                       min(o.date), max(o.date), count(o.id), c.opening_balance
                FROM admin_company ac
                JOIN company c ON c.company_id = ac.company_id
                JOIN legal_form lf ON lf.id = c.legal_form_id
                JOIN operation o ON o.company_id = ac.company_id AND o.user_id = ac.user_id
                GROUP BY c.company_id, c.company_name, c.company_inn, lf.code, c.industry, c.opening_balance
                ORDER BY c.company_id""").fetchall()
            ops = conn.execute(ADMIN_COMPANIES_SQL + """
                SELECT o.company_id, o.source_operation_id, o.date, o.amount, d.name, cp.inn, cp.name,
                       o.payment_purpose, o.balance_eod
                FROM admin_company ac
                JOIN operation o ON o.company_id = ac.company_id AND o.user_id = ac.user_id
                JOIN direction d ON d.id = o.direction_id
                LEFT JOIN counterparty cp ON cp.id = o.counterparty_id
                ORDER BY o.company_id, o.date, o.id""").fetchall()
    except psycopg.Error:
        raise DatabaseUnavailableError() from None

    dest.mkdir(parents=True, exist_ok=True)
    comp = pd.DataFrame([r[:8] for r in companies], columns=COMPANY_COLUMNS)
    comp["industry"] = comp["industry"].map(lambda v: INDUSTRY_ALIASES.get(v, v))
    opening = {r[0]: float(r[8]) if r[8] is not None else 0.0 for r in companies}
    df = pd.DataFrame(ops, columns=STATEMENT_COLUMNS)
    df["operation_date"] = pd.to_datetime(df["operation_date"])
    df["amount"] = df["amount"].astype(float)
    df["payment_purpose"] = df["payment_purpose"].fillna("")
    df["counterparty_inn"] = df["counterparty_inn"].astype("string")
    parts = []
    for company_id, part in df.groupby("company_id", sort=True):
        part = part.copy()
        if part["balance_eod"].isna().any():
            part["balance_eod"] = fill_balance(part, opening.get(company_id, 0.0))
        parts.append(part)
    df = pd.concat(parts, ignore_index=True) if parts else df
    df["balance_eod"] = df["balance_eod"].astype(float)
    df["operation_date"] = df["operation_date"].dt.strftime("%Y-%m-%d")
    comp.to_csv(dest / "companies.csv", sep=";", index=False, encoding="utf-8-sig")
    df[STATEMENT_COLUMNS].to_csv(dest / "all_operations.csv", sep=";", index=False, encoding="utf-8-sig")
    log.info("quality export: компаний %d, операций %d", len(comp), len(df))
    return len(comp)
