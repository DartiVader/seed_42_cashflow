package ru.seed.server.repository;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import ru.seed.server.dto.CompanyDTO;
import ru.seed.server.dto.CompanyFilter;
import ru.seed.server.utils.SqlConditions;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Repository
@RequiredArgsConstructor
public class CompanyRepository {

    private static final String SELECT_COMPANY_SQL =
            "select c.company_id, c.company_name, c.company_inn, lf.code as legal_form, c.industry ";

    private static final String FROM_USER_COMPANIES_SQL = """
            from company c
            join legal_form lf on lf.id = c.legal_form_id
            where c.user_id = :userId
            """;

    private static final Map<String, String> SORT_COLUMNS = Map.of(
            "companyId", "c.company_id",
            "companyName", "c.company_name",
            "companyInn", "c.company_inn",
            "legalForm", "lf.code",
            "industry", "c.industry");

    private final JdbcClient jdbcClient;

    public List<CompanyDTO> findPage(Long userId, CompanyFilter filter, int limit, long offset) {
        SqlConditions conditions = buildConditions(userId, filter)
                .param("limit", limit)
                .param("offset", offset);
        String orderBy = SqlConditions.orderBy(SORT_COLUMNS, filter.getSortField(), filter.getSortDirection(),
                "c.company_id", "c.company_id");
        String sql = SELECT_COMPANY_SQL + FROM_USER_COMPANIES_SQL + conditions.getSql() + orderBy
                + " limit :limit offset :offset";
        return jdbcClient.sql(sql)
                .params(conditions.getParams())
                .query((resultSet, rowNumber) -> toDto(resultSet))
                .list();
    }

    public long count(Long userId, CompanyFilter filter) {
        SqlConditions conditions = buildConditions(userId, filter);
        return jdbcClient.sql("select count(*) " + FROM_USER_COMPANIES_SQL + conditions.getSql())
                .params(conditions.getParams())
                .query(Long.class)
                .single();
    }

    public List<CompanyDTO> findAllByUserId(Long userId) {
        return jdbcClient.sql(SELECT_COMPANY_SQL + FROM_USER_COMPANIES_SQL + " order by c.company_id")
                .param("userId", userId)
                .query((resultSet, rowNumber) -> toDto(resultSet))
                .list();
    }

    public Map<String, Long> findOwnerIds(Collection<String> companyIds) {
        Map<String, Long> ownerIds = new HashMap<>();
        if (companyIds.isEmpty()) {
            return ownerIds;
        }
        jdbcClient.sql("select company_id, user_id from company where company_id in (:companyIds)")
                .param("companyIds", companyIds)
                .query(resultSet -> {
                    ownerIds.put(resultSet.getString("company_id"), resultSet.getLong("user_id"));
                });
        return ownerIds;
    }

    public Map<String, String> findCompanyIdsByInn(Collection<String> inns) {
        Map<String, String> companyIds = new HashMap<>();
        if (inns.isEmpty()) {
            return companyIds;
        }
        jdbcClient.sql("select company_id, company_inn from company where company_inn in (:inns)")
                .param("inns", inns)
                .query(resultSet -> {
                    companyIds.put(resultSet.getString("company_inn"), resultSet.getString("company_id"));
                });
        return companyIds;
    }

    public void insert(String companyId, Long userId, String companyName, String companyInn,
                       Short legalFormId, String industry) {
        jdbcClient.sql("""
                        insert into company (company_id, user_id, company_name, company_inn, legal_form_id, industry)
                        values (:companyId, :userId, :companyName, :companyInn, :legalFormId, :industry)
                        """)
                .param("companyId", companyId)
                .param("userId", userId)
                .param("companyName", companyName)
                .param("companyInn", companyInn)
                .param("legalFormId", legalFormId)
                .param("industry", industry)
                .update();
    }

    public void update(String companyId, String companyName, String companyInn, Short legalFormId, String industry) {
        jdbcClient.sql("""
                        update company
                        set company_name = :companyName, company_inn = :companyInn,
                            legal_form_id = :legalFormId, industry = :industry
                        where company_id = :companyId
                        """)
                .param("companyId", companyId)
                .param("companyName", companyName)
                .param("companyInn", companyInn)
                .param("legalFormId", legalFormId)
                .param("industry", industry)
                .update();
    }

    public void delete(String companyId) {
        jdbcClient.sql("delete from company where company_id = :companyId")
                .param("companyId", companyId)
                .update();
    }

    private SqlConditions buildConditions(Long userId, CompanyFilter filter) {
        return new SqlConditions()
                .param("userId", userId)
                .contains("c.company_id", "companyId", filter.getCompanyId())
                .contains("c.company_name", "companyName", filter.getCompanyName())
                .contains("c.company_inn", "companyInn", filter.getCompanyInn())
                .equalTo("lf.code", "legalForm", filter.getLegalForm())
                .equalTo("c.industry", "industry", filter.getIndustry());
    }

    private CompanyDTO toDto(ResultSet resultSet) throws SQLException {
        return new CompanyDTO(
                resultSet.getString("company_id"),
                resultSet.getString("company_name"),
                resultSet.getString("company_inn"),
                resultSet.getString("legal_form"),
                resultSet.getString("industry"));
    }
}
