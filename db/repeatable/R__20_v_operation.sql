-- Представление операций (запрос 1). Обычная вьюха: WHERE подставляется внутрь, работают индексы operation.
DROP VIEW IF EXISTS v_operation CASCADE;

CREATE VIEW v_operation AS
SELECT
    o.id                  AS operation_id,
    o.source_operation_id,
    o.company_id,
    o.date                AS operation_date,
    o.amount,
    o.direction_id,
    d.name                AS direction_name,
    d.sign,
    o.counterparty_id,
    c.inn                 AS counterparty_inn,
    c.name                AS counterparty_name,
    o.payment_purpose,
    o.balance_eod
FROM operation o
JOIN direction d          ON d.id = o.direction_id
LEFT JOIN counterparty c  ON c.id = o.counterparty_id;
