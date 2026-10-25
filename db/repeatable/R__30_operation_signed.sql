-- Операции с движением со знаком
DROP VIEW IF EXISTS operation_signed CASCADE;

CREATE VIEW operation_signed AS
SELECT o.*, d.name AS direction_name, d.sign, o.amount * d.sign AS signed_amount
FROM operation o
JOIN direction d ON d.id = o.direction_id;
