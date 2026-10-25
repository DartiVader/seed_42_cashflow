#!/usr/bin/env bash
# Применяет миграции к cashflow_bd.
#   DATABASE_URL=postgresql://postgres:pass@localhost:5432/cashflow_bd ./db/migrate.sh
#
# migrations/V*.sql  — выполняются один раз, по порядку номеров; факт записывается в schema_migrations.
# repeatable/R__*.sql — выполняются при каждом запуске (функции, представления), по порядку имён.
set -euo pipefail

DB_URL="${DATABASE_URL:?Укажите DATABASE_URL}"
DIR="$(cd "$(dirname "$0")" && pwd)"
export PGOPTIONS="${PGOPTIONS:-} -c client_min_messages=warning"   # без NOTICE «does not exist, skipping»
PSQL=(psql "$DB_URL" -v ON_ERROR_STOP=1 -q -X)

"${PSQL[@]}" -c "CREATE TABLE IF NOT EXISTS schema_migrations (
    version    VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);"

for f in $(ls "$DIR"/migrations/V*.sql | sort -V); do
    v="$(basename "$f")"
    done_=$("${PSQL[@]}" -tAc "SELECT 1 FROM schema_migrations WHERE version = '$v'")
    if [[ -z "$done_" ]]; then
        echo "→ $v"
        # файл и запись о нём — в одной транзакции: либо всё, либо ничего
        "${PSQL[@]}" -1 -f "$f" -c "INSERT INTO schema_migrations (version) VALUES ('$v')"
    fi
done

for f in $(ls "$DIR"/repeatable/R__*.sql | sort -V); do
    echo "↻ $(basename "$f")"
    "${PSQL[@]}" -1 -f "$f"
done

echo "Готово."
