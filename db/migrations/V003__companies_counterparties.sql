-- Компании, доступ пользователей к компаниям, контрагенты

CREATE TABLE company (
    company_id      VARCHAR(10)  PRIMARY KEY,                     -- C001…
    company_name    VARCHAR(255) NOT NULL,
    company_inn     VARCHAR(12)  NOT NULL UNIQUE
                    CHECK (company_inn ~ '^\d{10}(\d{2})?$'),     -- строка: ведущие нули сохраняются
    legal_form_id   SMALLINT     NOT NULL REFERENCES legal_form (id),
    industry        VARCHAR(100) NOT NULL,
    opening_balance NUMERIC(15,2)
);

CREATE TABLE users_company (
    user_id    BIGINT      NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    company_id VARCHAR(10) NOT NULL REFERENCES company (company_id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, company_id)
);
CREATE INDEX users_company_company_id_idx ON users_company (company_id);

CREATE TABLE counterparty (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inn  VARCHAR(12)  CHECK (inn ~ '^\d{10}(\d{2})?$'),          -- может быть NULL
    name VARCHAR(255) NOT NULL
);
-- контрагент = пара (ИНН, название); NULL-ИНН тоже участвует в уникальности
CREATE UNIQUE INDEX counterparty_inn_name_uq ON counterparty (COALESCE(inn, ''), name);
