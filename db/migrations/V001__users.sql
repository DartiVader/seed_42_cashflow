-- Пользователи и хэширование паролей

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- crypt() + gen_salt('bf') = bcrypt

CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Хэширование пароля при вставке и смене пароля.
-- Если пришёл готовый bcrypt-хэш (хэширует бэкенд), повторно не хэшируем.
CREATE FUNCTION users_hash_password() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.password_hash IS NOT DISTINCT FROM OLD.password_hash THEN
        RETURN NEW;
    END IF;
    IF NEW.password_hash !~ '^\$2[aby]\$\d{2}\$.{53}$' THEN
        NEW.password_hash := crypt(NEW.password_hash, gen_salt('bf', 12));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_hash_password
    BEFORE INSERT OR UPDATE OF password_hash ON users
    FOR EACH ROW EXECUTE FUNCTION users_hash_password();

-- created_at ставится при вставке и не меняется
CREATE FUNCTION users_keep_created_at() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at := now();
    ELSE
        NEW.created_at := OLD.created_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_created_at
    BEFORE INSERT OR UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION users_keep_created_at();
