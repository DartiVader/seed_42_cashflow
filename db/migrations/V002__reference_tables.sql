-- Справочники: направления операций и организационно-правовые формы

CREATE TABLE direction (
    id   SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    sign SMALLINT    NOT NULL CHECK (sign IN (-1, 0, 1))   -- amount * sign = движение со знаком
);
INSERT INTO direction (name, sign) VALUES ('Поступление', 1), ('Списание', -1);

CREATE TABLE legal_form (
    id         SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       VARCHAR(10)  NOT NULL UNIQUE,   -- ООО, ИП
    name       VARCHAR(255) NOT NULL,
    inn_length SMALLINT     NOT NULL CHECK (inn_length IN (10, 12))
);
INSERT INTO legal_form (code, name, inn_length) VALUES
    ('ООО', 'Общество с ограниченной ответственностью', 10),
    ('ИП',  'Индивидуальный предприниматель', 12);
