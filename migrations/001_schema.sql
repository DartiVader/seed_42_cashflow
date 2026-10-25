-- Схема БД Виталия (cashflow_bd v0.2), без изменений по смыслу. Каждый объект создаётся, только если его ещё
-- нет: на общей БД миграция ничего не меняет и не перезаписывает его функции, триггеры и представления,
-- а локально (docker compose, тесты) даёт ту же схему.

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- crypt() + gen_salt('bf') = bcrypt

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $migration$
BEGIN
    -- Хэширование пароля при вставке/смене; готовый bcrypt-хэш (бэкенд присылает именно его) не трогается
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'users_hash_password') THEN
        EXECUTE $fn$
        CREATE FUNCTION users_hash_password() RETURNS trigger AS $body$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.password_hash IS NOT DISTINCT FROM OLD.password_hash THEN
                RETURN NEW;
            END IF;
            IF NEW.password_hash !~ '^\$2[aby]\$\d{2}\$.{53}$' THEN
                NEW.password_hash := crypt(NEW.password_hash, gen_salt('bf', 12));
            END IF;
            RETURN NEW;
        END;
        $body$ LANGUAGE plpgsql
        $fn$;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_hash_password') THEN
        CREATE TRIGGER trg_users_hash_password
            BEFORE INSERT OR UPDATE OF password_hash ON users
            FOR EACH ROW EXECUTE FUNCTION users_hash_password();
    END IF;

    -- created_at: ставится при вставке и не меняется
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'users_keep_created_at') THEN
        EXECUTE $fn$
        CREATE FUNCTION users_keep_created_at() RETURNS trigger AS $body$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.created_at := now();
            ELSE
                NEW.created_at := OLD.created_at;
            END IF;
            RETURN NEW;
        END;
        $body$ LANGUAGE plpgsql
        $fn$;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_created_at') THEN
        CREATE TRIGGER trg_users_created_at
            BEFORE INSERT OR UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION users_keep_created_at();
    END IF;
END $migration$;

-- ---------- Справочник направлений ----------
CREATE TABLE IF NOT EXISTS direction (
    id   SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    sign SMALLINT    NOT NULL CHECK (sign IN (-1, 0, 1))
);
INSERT INTO direction (name, sign) VALUES ('Поступление', 1), ('Списание', -1) ON CONFLICT (name) DO NOTHING;

-- ---------- Справочник организационно-правовых форм ----------
CREATE TABLE IF NOT EXISTS legal_form (
    id         SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       VARCHAR(10)  NOT NULL UNIQUE,
    name       VARCHAR(255) NOT NULL,
    inn_length SMALLINT     NOT NULL CHECK (inn_length IN (10, 12))
);
INSERT INTO legal_form (code, name, inn_length) VALUES
    ('ООО', 'Общество с ограниченной ответственностью', 10),
    ('ИП',  'Индивидуальный предприниматель', 12)
ON CONFLICT (code) DO NOTHING;

-- ---------- Компании ----------
CREATE TABLE IF NOT EXISTS company (
    company_id      VARCHAR(10)  PRIMARY KEY,
    company_name    VARCHAR(255) NOT NULL,
    company_inn     VARCHAR(12)  NOT NULL UNIQUE CHECK (company_inn ~ '^\d{10}(\d{2})?$'),
    legal_form_id   SMALLINT     NOT NULL REFERENCES legal_form (id),
    industry        VARCHAR(100) NOT NULL,
    opening_balance NUMERIC(15,2)
);

-- ---------- Компании пользователя: кто загрузил или добавил данные компании ----------
CREATE TABLE IF NOT EXISTS users_company (
    user_id    BIGINT      NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    company_id VARCHAR(10) NOT NULL REFERENCES company (company_id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, company_id)
);
CREATE INDEX IF NOT EXISTS users_company_company_id_idx ON users_company (company_id);

-- ---------- Контрагенты: один контрагент = пара (ИНН, название) ----------
CREATE TABLE IF NOT EXISTS counterparty (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inn  VARCHAR(12)  CHECK (inn ~ '^\d{10}(\d{2})?$'),
    name VARCHAR(255) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS counterparty_inn_name_uq ON counterparty (COALESCE(inn, ''), name);

-- ---------- Сессии импорта и вставки ----------
CREATE TABLE IF NOT EXISTS sessions (
    id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Операции ----------
CREATE TABLE IF NOT EXISTS operation (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_operation_id VARCHAR(20),
    company_id          VARCHAR(10) NOT NULL REFERENCES company (company_id) ON DELETE CASCADE,
    date                DATE        NOT NULL,
    counterparty_id     BIGINT      REFERENCES counterparty (id),
    amount              NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    direction_id        SMALLINT    NOT NULL REFERENCES direction (id),
    payment_purpose     TEXT,
    balance_eod         NUMERIC(15,2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id             BIGINT      NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    session_id          INT         NOT NULL,
    CHECK (source_operation_id IS NOT NULL),
    UNIQUE (user_id, source_operation_id)   -- номер операции уникален в данных одного пользователя
);
-- Остаток на конец дня из выписки банка; у ручных операций и маркетплейсов — NULL
ALTER TABLE operation ADD COLUMN IF NOT EXISTS balance_eod NUMERIC(15,2);

-- Старая схема (владелец у компании): владелец переезжает в operation.user_id и users_company
DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'company' AND column_name = 'user_id') THEN
        ALTER TABLE operation ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users (id) ON DELETE RESTRICT;
        UPDATE operation o SET user_id = c.user_id FROM company c WHERE c.company_id = o.company_id AND o.user_id IS NULL;
        ALTER TABLE operation ALTER COLUMN user_id SET NOT NULL;
        INSERT INTO users_company (user_id, company_id)
        SELECT user_id, company_id FROM company WHERE user_id IS NOT NULL ON CONFLICT DO NOTHING;
        ALTER TABLE company ALTER COLUMN user_id DROP NOT NULL;
    END IF;
END $owner$;
CREATE INDEX IF NOT EXISTS operation_user_company_date_idx ON operation (user_id, company_id, date);
-- Поиск повторов при импорте: номер операции среди операций пользователя по компании
CREATE INDEX IF NOT EXISTS operation_user_company_source_idx ON operation (user_id, company_id, source_operation_id);
CREATE INDEX IF NOT EXISTS operation_company_date_idx ON operation (company_id, date);
CREATE INDEX IF NOT EXISTS operation_counterparty_idx ON operation (counterparty_id, date);
CREATE INDEX IF NOT EXISTS operation_session_id_idx ON operation (session_id);
CREATE INDEX IF NOT EXISTS operation_date_idx ON operation (date);

-- ---------- Категории ----------
CREATE TABLE IF NOT EXISTS categories (
    id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS operations_categories (
    operation_id BIGINT NOT NULL REFERENCES operation (id) ON DELETE CASCADE,
    category_id  INT    NOT NULL REFERENCES categories (id) ON DELETE RESTRICT,
    PRIMARY KEY (operation_id, category_id)
);
CREATE INDEX IF NOT EXISTS operations_categories_category_idx ON operations_categories (category_id);

-- У categories нет уникальности по имени: служебные категории добавляем, только если их ещё нет
INSERT INTO categories (name)
SELECT name FROM (VALUES ('Обязательный'), ('Регулярный'), ('Ежемесячно'), ('Ежемесячно (с пропусками)'),
                         ('Ежеквартально'), ('Раз в 2 месяца'), ('Сезонно')) AS seed (name)
WHERE NOT EXISTS (SELECT 1 FROM categories c WHERE c.name = seed.name);

DO $migration$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_views WHERE schemaname = current_schema() AND viewname = 'operation_signed') THEN
        CREATE VIEW operation_signed AS
        SELECT o.*, d.name AS direction_name, d.sign, o.amount * d.sign AS signed_amount
        FROM operation o JOIN direction d ON d.id = o.direction_id;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_views WHERE schemaname = current_schema() AND viewname = 'v_operation') THEN
        CREATE VIEW v_operation AS
        SELECT o.id AS operation_id, o.source_operation_id, o.company_id, o.date AS operation_date, o.amount,
               o.direction_id, d.name AS direction_name, d.sign, o.counterparty_id, c.inn AS counterparty_inn,
               c.name AS counterparty_name, o.payment_purpose, o.session_id, o.balance_eod, o.user_id
        FROM operation o
        JOIN direction d ON d.id = o.direction_id
        LEFT JOIN counterparty c ON c.id = o.counterparty_id;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'category_cadence_names') THEN
        EXECUTE $fn$
        CREATE FUNCTION category_cadence_names() RETURNS TEXT[]
        LANGUAGE sql IMMUTABLE AS $body$
            SELECT ARRAY['Ежемесячно', 'Ежемесячно (с пропусками)', 'Ежеквартально', 'Раз в 2 месяца', 'Сезонно']
        $body$
        $fn$;
    END IF;

    -- Операции за период с остатком на конец дня из выписки (NULL — остатка нет) и признаками категорий
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'get_operations_period') THEN
        EXECUTE $fn$
        CREATE FUNCTION get_operations_period(p_company_id VARCHAR, p_start DATE, p_end DATE)
        RETURNS TABLE (
            operation_id      BIGINT,
            operation_date    DATE,
            amount            NUMERIC,
            direction_name    VARCHAR,
            counterparty_inn  VARCHAR,
            counterparty_name VARCHAR,
            payment_purpose   TEXT,
            balance_eod       NUMERIC,
            is_nessery        BOOLEAN,
            is_regular        BOOLEAN,
            is_cadence        BOOLEAN,
            category_dop      BOOLEAN
        )
        LANGUAGE sql STABLE AS $body$
        WITH special AS (
            SELECT
                MAX(id) FILTER (WHERE name = 'Обязательный')                      AS mandatory_id,
                MAX(id) FILTER (WHERE name = 'Регулярный')                        AS regular_id,
                ARRAY_AGG(id) FILTER (WHERE name = ANY(category_cadence_names())) AS cadence_ids
            FROM categories
            WHERE name = ANY(ARRAY['Обязательный', 'Регулярный'] || category_cadence_names())
        )
        SELECT
            v.operation_id,
            v.operation_date,
            v.amount,
            v.direction_name,
            v.counterparty_inn,
            v.counterparty_name,
            v.payment_purpose,
            v.balance_eod,
            COALESCE(f.is_nessery,   FALSE),
            COALESCE(f.is_regular,   FALSE),
            COALESCE(f.is_cadence,   FALSE),
            COALESCE(f.category_dop, FALSE)
        FROM v_operation v
        CROSS JOIN special s
        LEFT JOIN LATERAL (
            SELECT
                bool_or(oc.category_id = s.mandatory_id)       AS is_nessery,
                bool_or(oc.category_id = s.regular_id)         AS is_regular,
                bool_or(oc.category_id = ANY(s.cadence_ids))   AS is_cadence,
                bool_or(oc.category_id <> s.mandatory_id
                        AND oc.category_id <> s.regular_id
                        AND NOT oc.category_id = ANY(s.cadence_ids)) AS category_dop
            FROM operations_categories oc
            WHERE oc.operation_id = v.operation_id
        ) f ON TRUE
        WHERE v.company_id = p_company_id
          AND v.operation_date BETWEEN p_start AND p_end
        ORDER BY v.operation_date, v.operation_id;
        $body$
        $fn$;
    END IF;
END $migration$;
