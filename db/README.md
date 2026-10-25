# База данных cashflow_bd

```
db/
├── create_database.sql        # создание БД — один раз, вручную
├── migrate.sh                 # применение миграций
├── migrations/                # изменения схемы, выполняются ОДИН раз
│   ├── V001__users.sql
│   ├── V002__reference_tables.sql
│   ├── V003__companies_counterparties.sql
│   ├── V004__sessions_operations.sql
│   └── V005__categories.sql
├── repeatable/                # функции и представления, выполняются КАЖДЫЙ раз
│   ├── R__10_category_cadence_names.sql
│   ├── R__20_v_operation.sql
│   ├── R__30_operation_signed.sql
│   └── R__40_get_operations_period.sql
└── scripts/                   # служебное, вручную
    ├── load_operations.sql
    ├── truncate_all.sql
    └── drop_all.sql
```

## Развернуть с нуля

```bash
psql -U postgres -f db/create_database.sql
export DATABASE_URL=postgresql://postgres:pass@localhost:5432/cashflow_bd
./db/migrate.sh
psql "$DATABASE_URL" -v csv=data/all_operations.csv -v user_id=1 -f db/scripts/load_operations.sql
```

## Правила

1. **Применённую миграцию не редактируем.** Нужно изменить таблицу — новый файл
   `V006__что_меняем.sql` с `ALTER TABLE …`. Иначе у коллег, уже применивших V00x, базы разойдутся.
2. **Номер — следующий по порядку.** Перед коммитом сделайте `git pull`: если коллега уже занял номер, возьмите следующий.
3. **Функции и представления — в `repeatable/`, их можно править.** Файл начинается с `DROP … IF EXISTS`,
   поэтому меняются и тип результата, и состав колонок. Номер в имени (`R__20_`) задаёт порядок: сначала то, от чего зависят.
4. **Одна миграция — одно логическое изменение**, каждая выполняется в транзакции.
5. **Данные и секреты не коммитим**: CSV-выписки, дампы, пароли, `.env`.
6. Кодировка UTF-8 без BOM, переводы строк LF (см. `.gitattributes`).
