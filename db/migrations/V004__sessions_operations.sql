-- Сессии импорта и операции

CREATE TABLE sessions (
    id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE operation (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_operation_id VARCHAR(20)   NOT NULL,       -- номер из выписки (C001-000001)
    company_id          VARCHAR(10)   NOT NULL REFERENCES company (company_id) ON DELETE CASCADE,
    date                DATE          NOT NULL,
    counterparty_id     BIGINT        REFERENCES counterparty (id),
    amount              NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    direction_id        SMALLINT      NOT NULL REFERENCES direction (id),
    payment_purpose     TEXT,
    balance_eod         NUMERIC(15,2),                -- остаток на конец дня из выписки
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    user_id             BIGINT        NOT NULL REFERENCES users (id) ON DELETE RESTRICT,   -- кто загрузил
    session_id          INT           NOT NULL REFERENCES sessions (id) ON DELETE RESTRICT
);
CREATE INDEX operation_company_date_idx ON operation (company_id, date);
CREATE INDEX operation_counterparty_idx ON operation (counterparty_id, date);
CREATE INDEX operation_session_id_idx   ON operation (session_id);
CREATE INDEX operation_user_idx         ON operation (user_id);
CREATE INDEX operation_date_idx         ON operation (date);
