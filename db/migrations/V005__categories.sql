-- Категории (общие для всех компаний) и связь операция ↔ категория

CREATE TABLE categories (
    id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE operations_categories (
    operation_id BIGINT NOT NULL REFERENCES operation (id) ON DELETE CASCADE,
    category_id  INT    NOT NULL REFERENCES categories (id) ON DELETE RESTRICT,
    PRIMARY KEY (operation_id, category_id)
);
CREATE INDEX operations_categories_category_idx ON operations_categories (category_id);

-- Служебные категории: признаки и периодичность
INSERT INTO categories (name) VALUES
    ('Обязательный'),
    ('Регулярный'),
    ('Ежемесячно'),
    ('Ежемесячно (с пропусками)'),
    ('Ежеквартально'),
    ('Раз в 2 месяца'),
    ('Сезонно')
ON CONFLICT (name) DO NOTHING;
