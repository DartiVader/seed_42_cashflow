package ru.seed.server.repository;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import ru.seed.server.dto.OperationCsvRow;
import ru.seed.server.dto.OperationDTO;
import ru.seed.server.dto.OperationRequest;

import java.time.LocalDate;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
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

    private static final String COMPANY_FILTER_SQL = " and o.company_id = :companyId";

    private final JdbcClient jdbcClient;
    private final JdbcTemplate jdbcTemplate;

    public List<OperationDTO> findPage(Long userId, String companyId, int limit, long offset) {
        String sql = """
                select o.id, o.company_id, o.source_operation_id, o.date, o.amount, d.name as direction,
                       cp.inn as counterparty_inn, cp.name as counterparty_name, o.payment_purpose
                """ + FROM_USER_OPERATIONS_SQL + companyFilter(companyId)
                + " order by o.date desc, o.id desc limit :limit offset :offset";
        return jdbcClient.sql(sql)
                .param("userId", userId)
                .param("companyId", companyId)
                .param("limit", limit)
                .param("offset", offset)
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

    public long count(Long userId, String companyId) {
        return jdbcClient.sql("select count(*) " + FROM_USER_OPERATIONS_SQL + companyFilter(companyId))
                .param("userId", userId)
                .param("companyId", companyId)
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

    private String companyFilter(String companyId) {
        if (companyId == null) {
            return "";
        }
        return COMPANY_FILTER_SQL;
    }
}
