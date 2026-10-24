package ru.seed.server.utils;

import java.util.HashMap;
import java.util.Map;

public class SqlConditions {

    private final StringBuilder sql = new StringBuilder();
    private final Map<String, Object> params = new HashMap<>();

    public SqlConditions param(String name, Object value) {
        params.put(name, value);
        return this;
    }

    public SqlConditions equalTo(String column, String paramName, String value) {
        if (value == null || value.isBlank()) {
            return this;
        }
        sql.append(" and ").append(column).append(" = :").append(paramName);
        params.put(paramName, value.trim());
        return this;
    }

    public SqlConditions contains(String column, String paramName, String value) {
        if (value == null || value.isBlank()) {
            return this;
        }
        sql.append(" and ").append(column).append(" ilike :").append(paramName);
        params.put(paramName, "%" + escapeLike(value.trim()) + "%");
        return this;
    }

    public SqlConditions atLeast(String column, String paramName, Object value) {
        if (value == null) {
            return this;
        }
        sql.append(" and ").append(column).append(" >= :").append(paramName);
        params.put(paramName, value);
        return this;
    }

    public SqlConditions atMost(String column, String paramName, Object value) {
        if (value == null) {
            return this;
        }
        sql.append(" and ").append(column).append(" <= :").append(paramName);
        params.put(paramName, value);
        return this;
    }

    public String getSql() {
        return sql.toString();
    }

    public Map<String, Object> getParams() {
        return params;
    }

    public static String orderBy(Map<String, String> sortColumns, String sortField, String sortDirection,
                                 String defaultOrder, String tieBreaker) {
        String column = sortField == null ? null : sortColumns.get(sortField);
        if (column == null) {
            return " order by " + defaultOrder;
        }
        String direction = "desc".equalsIgnoreCase(sortDirection) ? "desc" : "asc";
        return " order by " + column + " " + direction + " nulls last, " + tieBreaker + " " + direction;
    }

    private static String escapeLike(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
