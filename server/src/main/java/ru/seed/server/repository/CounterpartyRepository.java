package ru.seed.server.repository;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

@Repository
@RequiredArgsConstructor
public class CounterpartyRepository {

    private final JdbcClient jdbcClient;

    public Map<String, Long> findIdsByInn(Collection<String> inns) {
        Map<String, Long> ids = new HashMap<>();
        if (inns.isEmpty()) {
            return ids;
        }
        jdbcClient.sql("select id, inn from counterparty where inn in (:inns) order by id")
                .param("inns", inns)
                .query(resultSet -> {
                    String inn = resultSet.getString("inn");
                    if (!ids.containsKey(inn)) {
                        ids.put(inn, resultSet.getLong("id"));
                    }
                });
        return ids;
    }

    public Map<String, Long> findIdsByNameWithoutInn(Collection<String> names) {
        Map<String, Long> ids = new HashMap<>();
        if (names.isEmpty()) {
            return ids;
        }
        jdbcClient.sql("select id, name from counterparty where inn is null and name in (:names)")
                .param("names", names)
                .query(resultSet -> {
                    ids.put(resultSet.getString("name"), resultSet.getLong("id"));
                });
        return ids;
    }

    public Long insert(String inn, String name) {
        return jdbcClient.sql("insert into counterparty (inn, name) values (:inn, :name) returning id")
                .param("inn", inn)
                .param("name", name)
                .query(Long.class)
                .single();
    }
}
