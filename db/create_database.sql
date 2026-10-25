-- Создание базы cashflow_bd. Выполняется ОДИН раз, отдельно от миграций.
--   psql -U postgres -f db/create_database.sql
-- Локаль ru_RU.UTF-8 должна быть установлена в системе/контейнере
-- (в образе postgres: localedef -i ru_RU -f UTF-8 ru_RU.UTF-8). Если её нет — уберите LC_*.

CREATE DATABASE cashflow_bd
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'ru_RU.UTF-8'
    LC_CTYPE = 'ru_RU.UTF-8'
    TEMPLATE = template0;
