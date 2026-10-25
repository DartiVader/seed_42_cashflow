-- Список категорий-периодичностей (используется в get_operations_period)
CREATE OR REPLACE FUNCTION category_cadence_names() RETURNS TEXT[]
LANGUAGE sql IMMUTABLE AS $$
    SELECT ARRAY['Ежемесячно', 'Ежемесячно (с пропусками)', 'Ежеквартально', 'Раз в 2 месяца', 'Сезонно']
$$;
