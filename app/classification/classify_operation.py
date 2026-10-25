"""
classify_operation.py

Классификация операций одной сессии загрузки (sessions.id) с полной историей контрагентов
и запись категорий в operations_categories.

Input
-----
  session_id : int — id сессии загрузки (operation.session_id)
  connection : psycopg.Connection (синхронный)
  as_of      : дата начала окна: в расчёт идут операции с operation_date >= as_of. None — вся история
  config     : overrides for analyze_payments.DEFAULT_CONFIG

Returns
-------
DataFrame[operation_id, is_regular, cadence, mandatory, category]

  - every operation of the session (from as_of) is present
  - counterparty history operations that become regular (`is_regular=True`)
    are also present
"""
import logging
import warnings
from datetime import date

import pandas as pd
import psycopg

from app.classification.analyze_payments import analyze_payments

log = logging.getLogger("backend.classification")

# Тот же запрос, что был с :params для pandas.read_sql, — с параметрами psycopg и без LIMIT/OFFSET
# История только этого пользователя: компания общая, у каждого пользователя в ней свои операции.
# user_id берём из operation — в v_operation его может не быть
QUERY = """
SELECT v.operation_id, v.operation_date, v.amount, v.direction_name, v.counterparty_id,
       v.counterparty_inn, v.counterparty_name, v.payment_purpose
FROM v_operation v
JOIN operation o ON o.id = v.operation_id
WHERE v.company_id = %(companyId)s
  AND o.user_id = %(userId)s
  AND (%(operationIds)s::bigint[] IS NULL OR v.operation_id = ANY(%(operationIds)s::bigint[]))
  AND (%(startOperationDate)s::date IS NULL OR v.operation_date >= %(startOperationDate)s::date)
  AND (%(counterpartyIds)s::bigint[] IS NULL OR v.counterparty_id = ANY(%(counterpartyIds)s::bigint[]))
ORDER BY v.operation_date, v.operation_id
"""

# Один запрос: компании сессии, их пользователь (сессия принадлежит одному), контрагенты и операции сессии
SESSION_QUERY = """
SELECT company_id,
       user_id,
       array_agg(DISTINCT counterparty_id) FILTER (WHERE counterparty_id IS NOT NULL) AS counterparty_ids,
       array_agg(id) AS operation_ids
FROM operation
WHERE session_id = %(sessionId)s
GROUP BY company_id, user_id
ORDER BY company_id, user_id
"""

OUTPUT_COLUMNS = ["operation_id", "is_regular", "cadence", "mandatory", "category"]

RESULT_COLUMNS = [
    "operation_id", "operation_date", "amount", "direction", "counterparty_id",
    "counterparty_inn", "counterparty_name", "payment_purpose",
]

REGULAR_CATEGORY = "Регулярный"
MANDATORY_CATEGORY = "Обязательный"


# ============================ INTERNAL HELPERS ==============================
def _fetch(connection: psycopg.Connection, company_id: str, user_id: int,
           operation_ids: list[int] | None = None, counterparty_ids: list[int] | None = None,
           as_of: date | None = None) -> pd.DataFrame:
    """Run the query for the user's operations with optional operationIds / counterpartyIds and start date as_of."""
    params = {
        "companyId":          company_id,
        "userId":             user_id,
        "operationIds":       operation_ids,      # None = no filter
        "startOperationDate": as_of,              # None = no filter
        "counterpartyIds":    counterparty_ids,   # None = no filter
    }
    with connection.cursor() as cur:
        cur.execute(QUERY, params)
        columns = [c.name for c in cur.description]
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    df = pd.DataFrame(rows, columns=columns)
    df["amount"] = df["amount"].astype(float)          # numeric приходит как Decimal
    df["counterparty_inn"] = df["counterparty_inn"].astype("string")  # ИНН — строкой
    return df.rename(columns={"direction_name": "direction"})


def _classify_company(connection: psycopg.Connection, company_id: str, user_id: int, session_op_ids: list[int],
                      cp_ids: list[int], as_of: date | None, config: dict | None) -> pd.DataFrame:
    """Шаги исходной classify_operations_by_id для одной компании сессии."""
    initial_ids = set(session_op_ids)

    # ── операции сессии без контрагента: значения по умолчанию ────────────
    if not cp_ids:
        empty = pd.DataFrame({"operation_id": sorted(initial_ids)})
        empty["is_regular"] = False
        empty["cadence"] = None
        empty["mandatory"] = False
        empty["category"] = None
        return empty[OUTPUT_COLUMNS]

    # ── все операции этих контрагентов компании с даты as_of ─────────────
    counterparty_ops = _fetch(connection, company_id, user_id, counterparty_ids=cp_ids, as_of=as_of)
    if counterparty_ops.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    counterparty_ops = (counterparty_ops
                        .drop_duplicates(subset=["operation_id"], keep="first")
                        .reset_index(drop=True))

    # ── classification pipeline; as_of — начало окна ─────────────────────
    with warnings.catch_warnings():
        # без производственного календаря analyze_payments предупреждает на каждый вызов
        warnings.filterwarnings("ignore", message="business_day_calendar не задан")
        streams, _prognosis, all_payments = analyze_payments(
            counterparty_ops, as_of=as_of, horizon_days=0, config=config,
        )
    if all_payments.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # ── keep policy: all session ops + regular counterparty ops ───────────
    is_initial    = all_payments["operation_id"].isin(initial_ids)
    is_cp_regular = (~is_initial) & all_payments["is_regular"].astype(bool)
    result        = all_payments.loc[is_initial | is_cp_regular].copy()

    # ── attach cadence (stream-level, not row-level) ──────────────────────
    if not streams.empty and not result.empty:
        stream_to_cadence = dict(zip(streams["stream_id"], streams["cadence"]))
        result["cadence"] = result["stream_id"].map(stream_to_cadence)
    else:
        result["cadence"] = None

    out = result[["operation_id", "is_regular", "cadence", "mandatory", "category"]]
    return out.reset_index(drop=True)[OUTPUT_COLUMNS]


def _labels(row) -> list[str]:
    """Названия категорий операции: is_regular → «Регулярный», cadence, mandatory → «Обязательный», category."""
    names = []
    if bool(row.is_regular):
        names.append(REGULAR_CATEGORY)
    if isinstance(row.cadence, str) and row.cadence.strip():
        names.append(row.cadence.strip())
    if bool(row.mandatory):
        names.append(MANDATORY_CATEGORY)
    if isinstance(row.category, str) and row.category.strip():
        names.append(row.category.strip())
    return names


def _category_ids(connection: psycopg.Connection, names: set[str]) -> dict[str, int]:
    """lower(name) → id; категории, которых ещё нет, создаются."""
    by_lower: dict[str, str] = {}
    for name in sorted(names):
        by_lower.setdefault(name.lower(), name)
    with connection.cursor() as cur:
        cur.execute("SELECT lower(name), min(id) FROM categories WHERE lower(name) = ANY(%s) GROUP BY lower(name)",
                    [list(by_lower)])
        ids = {lower: category_id for lower, category_id in cur.fetchall()}
        for lower, name in by_lower.items():
            if lower not in ids:
                cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING id", [name])
                ids[lower] = cur.fetchone()[0]
    return ids


def save_categories(connection: psycopg.Connection, out: pd.DataFrame) -> int:
    """Перезаписывает категории операций из out: удаляет старые связи, вставляет новые. → число связей."""
    if out.empty:
        return 0
    pairs = [(int(row.operation_id), name) for row in out.itertuples(index=False) for name in _labels(row)]
    operation_ids = sorted({int(i) for i in out["operation_id"]})
    with connection.cursor() as cur:
        cur.execute("DELETE FROM operations_categories WHERE operation_id = ANY(%s)", [operation_ids])
        if not pairs:
            return 0
        ids = _category_ids(connection, {name for _, name in pairs})
        rows = sorted({(operation_id, ids[name.lower()]) for operation_id, name in pairs})
        cur.executemany(
            "INSERT INTO operations_categories (operation_id, category_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            rows)
    return len(rows)


# =============================== PUBLIC API =================================
def classify_operations_by_session_id(
    session_id: int,
    connection: psycopg.Connection,
    as_of: date | None = None,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Classify the operations of the session and any counterparty history that ends up
    classified as a regular stream; write the categories to operations_categories.

    Каждая компания — своя транзакция: ошибка в одной не откатывает уже записанные.

    Returns
    -------
    DataFrame with columns [operation_id, is_regular, cadence, mandatory, category]
    (category names are in Russian, as produced by analyze_payments).
    """
    with connection.cursor() as cur:
        cur.execute(SESSION_QUERY, {"sessionId": session_id})
        companies = cur.fetchall()

    frames = []
    for company_id, user_id, cp_ids, session_op_ids in companies:
        with connection.transaction():
            out = _classify_company(connection, company_id, user_id, session_op_ids, cp_ids or [], as_of, config)
            links = save_categories(connection, out)
        log.info("classified session_id=%s user_id=%s company_id=%s operations=%d links=%d",
                 session_id, user_id, company_id, len(out), links)
        frames.append(out)

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.concat(frames, ignore_index=True)[OUTPUT_COLUMNS]
