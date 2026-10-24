package ru.seed.server.repository;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import ru.seed.server.dto.OperationCsvRow;
import ru.seed.server.dto.OperationDTO;
import ru.seed.server.dto.OperationFilter;
import ru.seed.server.dto.OperationRequest;
import ru.seed.server.utils.SqlConditions;

import java.time.LocalDate;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

@Repository
@RequiredArgsConstructor
public class OperationRepository {

    private static final String INSERT_SQL = """
            insert into operation (source_operation_id, company_id, date, counterparty_id, amount, direction_id, payment_purpose)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict (source_operation_id) do nothing
            """;

    private static final String FROM_USER_OPERATIONS_SQL = """
            from operation o
            join company c on c.company_id = o.company_id
            join direction d on d.id = o.direction_id
            left join counterparty cp on cp.id = o.counterparty_id
            where c.user_id = :userId and not o.is_future
            """;

    private static final Map<String, String> SORT_COLUMNS = Map.of(
            "date", "o.date",
            "companyId", "o.company_id",
            "operationId", "o.source_operation_id",
            "amount", "o.amount",
            "direction", "d.name",
            "counterpartyName", "cp.name",
            "counterpartyInn", "cp.inn",
            "paymentPurpose", "o.payment_purpose");

    private final JdbcClient jdbcClient;
    private final JdbcTemplate jdbcTemplate;

    public List<OperationDTO> findPage(Long userId, OperationFilter filter, int limit, long offset) {
        SqlConditions conditions = buildConditions(userId, filter)
                .param("limit", limit)
                .param("offset", offset);
        String orderBy = SqlConditions.orderBy(SORT_COLUMNS, filter.getSortField(), filter.getSortDirection(),
                "o.date desc, o.id desc", "o.id");
        String sql = """
                select o.id, o.company_id, o.source_operation_id, o.date, o.amount, d.name as direction,
                       cp.inn as counterparty_inn, cp.name as counterparty_name, o.payment_purpose
                """ + FROM_USER_OPERATIONS_SQL + conditions.getSql() + orderBy + " limit :limit offset :offset";
        return jdbcClient.sql(sql)
                .params(conditions.getParams())
                .query((resultSet, rowNumber) -> new OperationDTO(
                        resultSet.getLong("id"),
                        resultSet.getString("company_id"),
                        resultSet.getString("source_operation_id"),
                        resultSet.getObject("date", LocalDate.class),
                        resultSet.getBigDecimal("amount"),
                        resultSet.getString("direction"),
                        resultSet.getString("counterparty_inn"),
                        resultSet.getString("counterparty_name"),
                        resultSet.getString("payment_purpose")))
                .list();
    }

    public long count(Long userId, OperationFilter filter) {
        SqlConditions conditions = buildConditions(userId, filter);
        return jdbcClient.sql("select count(*) " + FROM_USER_OPERATIONS_SQL + conditions.getSql())
                .params(conditions.getParams())
                .query(Long.class)
                .single();
    }

    public boolean existsForUser(Long id, Long userId) {
        return jdbcClient.sql("select count(*) " + FROM_USER_OPERATIONS_SQL + " and o.id = :id")
                .param("userId", userId)
                .param("id", id)
                .query(Long.class)
                .single() > 0;
    }

    public Optional<Long> findIdBySourceOperationId(String sourceOperationId) {
        return jdbcClient.sql("select id from operation where source_operation_id = :sourceOperationId")
                .param("sourceOperationId", sourceOperationId)
                .query(Long.class)
                .optional();
    }

    public Set<String> findExistingSourceIds(Collection<String> sourceOperationIds) {
        if (sourceOperationIds.isEmpty()) {
            return new HashSet<>();
        }
        List<String> existing = jdbcClient.sql(
                        "select source_operation_id from operation where source_operation_id in (:ids)")
                .param("ids", sourceOperationIds)
                .query(String.class)
                .list();
        return new HashSet<>(existing);
    }

    public void insertAll(List<OperationCsvRow> rows) {
        if (rows.isEmpty()) {
            return;
        }
        jdbcTemplate.batchUpdate(INSERT_SQL, rows, rows.size(), (statement, row) -> {
            statement.setString(1, row.getSourceOperationId());
            statement.setString(2, row.getCompanyId());
            statement.setObject(3, row.getDate());
            statement.setLong(4, row.getCounterpartyId());
            statement.setBigDecimal(5, row.getAmount());
            statement.setShort(6, row.getDirectionId());
            statement.setString(7, row.getPaymentPurpose());
        });
    }

    public Long insert(OperationRequest request, Long counterpartyId, Short directionId) {
        return jdbcClient.sql("""
                        insert into operation (source_operation_id, company_id, date, counterparty_id, amount,
                                               direction_id, payment_purpose)
                        values (:operationId, :companyId, :date, :counterpartyId, :amount, :directionId, :paymentPurpose)
                        returning id
                        """)
                .param("operationId", request.getOperationId())
                .param("companyId", request.getCompanyId())
                .param("date", request.getDate())
                .param("counterpartyId", counterpartyId)
                .param("amount", request.getAmount())
                .param("directionId", directionId)
                .param("paymentPurpose", request.getPaymentPurpose())
                .query(Long.class)
                .single();
    }

    public void update(Long id, OperationRequest request, Long counterpartyId, Short directionId) {
        jdbcClient.sql("""
                        update operation
                        set source_operation_id = :operationId, company_id = :companyId, date = :date,
                            counterparty_id = :counterpartyId, amount = :amount, direction_id = :directionId,
                            payment_purpose = :paymentPurpose
                        where id = :id
                        """)
                .param("id", id)
                .param("operationId", request.getOperationId())
                .param("companyId", request.getCompanyId())
                .param("date", request.getDate())
                .param("counterpartyId", counterpartyId)
                .param("amount", request.getAmount())
                .param("directionId", directionId)
                .param("paymentPurpose", request.getPaymentPurpose())
                .update();
    }

    public void delete(Long id) {
        jdbcClient.sql("delete from operation where id = :id")
                .param("id", id)
                .update();
    }

    private SqlConditions buildConditions(Long userId, OperationFilter filter) {
        return new SqlConditions()
                .param("userId", userId)
                .equalTo("o.company_id", "companyId", filter.getCompanyId())
                .contains("o.source_operation_id", "operationId", filter.getOperationId())
                .contains("cp.name", "counterpartyName", filter.getCounterpartyName())
                .contains("cp.inn", "counterpartyInn", filter.getCounterpartyInn())
                .contains("o.payment_purpose", "paymentPurpose", filter.getPaymentPurpose())
                .equalTo("d.name", "direction", filter.getDirection())
                .atLeast("o.amount", "amountFrom", filter.getAmountFrom())
                .atMost("o.amount", "amountTo", filter.getAmountTo())
                .atLeast("o.date", "dateFrom", filter.getDateFrom())
                .atMost("o.date", "dateTo", filter.getDateTo());
    }
}
