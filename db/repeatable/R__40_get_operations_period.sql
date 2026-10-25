-- Операции компании за период: остаток на конец дня из выписки и признаки категорий (запрос 2)
DROP FUNCTION IF EXISTS get_operations_period(VARCHAR, DATE, DATE);

CREATE FUNCTION get_operations_period(
    p_company_id VARCHAR,
    p_start      DATE,
    p_end        DATE
)
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
    cadence           VARCHAR,    -- название периодичности или NULL
    category_dop      VARCHAR     -- название прочей категории или NULL
)
LANGUAGE sql STABLE AS $$
SELECT
    v.operation_id,
    v.operation_date,
    v.amount,
    v.direction_name,
    v.counterparty_inn,
    v.counterparty_name,
    v.payment_purpose,
    v.balance_eod,
    COALESCE(f.is_nessery, FALSE),
    COALESCE(f.is_regular, FALSE),
    f.cadence,
    f.category_dop
FROM v_operation v
LEFT JOIN LATERAL (
    SELECT
        bool_or(c.name = 'Обязательный')                                  AS is_nessery,
        bool_or(c.name = 'Регулярный')                                    AS is_regular,
        MAX(c.name) FILTER (WHERE c.name = ANY(category_cadence_names())) AS cadence,
        MAX(c.name) FILTER (WHERE c.name NOT IN ('Обязательный', 'Регулярный')
                              AND NOT c.name = ANY(category_cadence_names())) AS category_dop
    FROM operations_categories oc
    JOIN categories c ON c.id = oc.category_id
    WHERE oc.operation_id = v.operation_id
) f ON TRUE
WHERE v.company_id = p_company_id
  AND v.operation_date BETWEEN p_start AND p_end
ORDER BY v.operation_date, v.operation_id;
$$;
