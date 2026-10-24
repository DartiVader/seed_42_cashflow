package ru.seed.server.repository;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import ru.seed.server.dto.CompanyDTO;

import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Repository
@RequiredArgsConstructor
public class CompanyRepository {

    private final JdbcClient jdbcClient;

    public List<CompanyDTO> findPageByUserId(Long userId, int limit, long offset) {
        return jdbcClient.sql("""
                        select c.company_id, c.company_name, c.company_inn, lf.code as legal_form, c.industry
                        from company c
                        join legal_form lf on lf.id = c.legal_form_id
                        where c.user_id = :userId
                        order by c.company_id
                        limit :limit offset :offset
                        """)
                .param("userId", userId)
                .param("limit", limit)
                .param("offset", offset)
                .query((resultSet, rowNumber) -> new CompanyDTO(
                        resultSet.getString("company_id"),
                        resultSet.getString("company_name"),
                        resultSet.getString("company_inn"),
                        resultSet.getString("legal_form"),
                        resultSet.getString("industry")))
                .list();
    }

    public long countByUserId(Long userId) {
        return jdbcClient.sql("select count(*) from company where user_id = :userId")
                .param("userId", userId)
                .query(Long.class)
                .single();
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
}
