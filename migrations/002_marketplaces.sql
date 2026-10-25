-- Подключения компаний к маркетплейсам (OZON, Wildberries, Яндекс Маркет) по API-ключу.
-- Ключи наружу не отдаются: фронт видит только последние 4 символа.
CREATE TABLE IF NOT EXISTS marketplace_connection (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    company_id   VARCHAR(10) NOT NULL REFERENCES company (company_id) ON DELETE CASCADE,
    marketplace  VARCHAR(10) NOT NULL CHECK (marketplace IN ('ozon', 'wb', 'yandex')),
    credentials  JSONB       NOT NULL,   -- ozon: client_id, api_key; wb: token; yandex: token, business_id
    last_sync_at TIMESTAMPTZ,
    last_result  JSONB,                  -- итог последней загрузки: принято, пропущено, отклонено, период
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, company_id, marketplace)
);
CREATE INDEX IF NOT EXISTS marketplace_connection_user_idx ON marketplace_connection (user_id);

-- Компания общая для пользователей: подключение — своё у каждого пользователя компании
DO $mp$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'marketplace_connection_company_id_marketplace_key') THEN
        ALTER TABLE marketplace_connection DROP CONSTRAINT marketplace_connection_company_id_marketplace_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'marketplace_connection'::regclass AND contype = 'u') THEN
        ALTER TABLE marketplace_connection ADD UNIQUE (user_id, company_id, marketplace);
    END IF;
END $mp$;
