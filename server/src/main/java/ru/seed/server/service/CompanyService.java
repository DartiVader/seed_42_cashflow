package ru.seed.server.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.CompanyDTO;
import ru.seed.server.dto.CompanyRequest;
import ru.seed.server.dto.PageDTO;
import ru.seed.server.exception.AlreadyExistsException;
import ru.seed.server.exception.CompanyNotFoundException;
import ru.seed.server.exception.InvalidFieldException;
import ru.seed.server.exception.Response;
import ru.seed.server.model.LegalForm;
import ru.seed.server.repository.CompanyRepository;
import ru.seed.server.repository.LegalFormRepository;
import ru.seed.server.utils.PageUtils;
import ru.seed.server.utils.ResponseUtils;

import java.util.List;
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class CompanyService {

    private final CompanyRepository companyRepository;
    private final LegalFormRepository legalFormRepository;

    @Transactional(readOnly = true)
    public Response<PageDTO<CompanyDTO>> getCompanies(Long userId, int page, int size) {
        int pageNumber = PageUtils.normalizePage(page);
        int pageSize = PageUtils.normalizeSize(size);
        List<CompanyDTO> items = companyRepository.findPageByUserId(
                userId, pageSize, PageUtils.offset(pageNumber, pageSize));
        long total = companyRepository.countByUserId(userId);
        return ResponseUtils.responseSuccess("getCompanies", PageUtils.of(items, pageNumber, pageSize, total));
    }

    @Transactional
    public Response<CompanyDTO> createCompany(Long userId, CompanyRequest request) {
        CompanyDTO company = normalize(request.getCompanyId(), request);
        if (companyRepository.findOwnerIds(Set.of(company.getCompanyId())).containsKey(company.getCompanyId())) {
            throw new AlreadyExistsException("companyId", "Компания с таким кодом уже есть");
        }
        LegalForm legalForm = findLegalForm(company);
        checkInnIsFree(company);
        companyRepository.insert(company.getCompanyId(), userId, company.getCompanyName(), company.getCompanyInn(),
                legalForm.getId(), company.getIndustry());
        log.info("Company created, userId={}, companyId={}", userId, company.getCompanyId());
        return ResponseUtils.responseSuccess("createCompany", company);
    }

    @Transactional
    public Response<CompanyDTO> updateCompany(Long userId, String companyId, CompanyRequest request) {
        checkOwner(userId, companyId);
        CompanyDTO company = normalize(companyId, request);
        LegalForm legalForm = findLegalForm(company);
        checkInnIsFree(company);
        companyRepository.update(companyId, company.getCompanyName(), company.getCompanyInn(),
                legalForm.getId(), company.getIndustry());
        return ResponseUtils.responseSuccess("updateCompany", company);
    }

    @Transactional
    public Response<Void> deleteCompany(Long userId, String companyId) {
        checkOwner(userId, companyId);
        companyRepository.delete(companyId);
        log.info("Company deleted, userId={}, companyId={}", userId, companyId);
        return ResponseUtils.responseSuccess("deleteCompany", null);
    }

    private CompanyDTO normalize(String companyId, CompanyRequest request) {
        return new CompanyDTO(companyId.trim(), request.getCompanyName().trim(), request.getCompanyInn().trim(),
                request.getLegalForm().trim(), request.getIndustry().trim());
    }

    private void checkOwner(Long userId, String companyId) {
        Long ownerId = companyRepository.findOwnerIds(Set.of(companyId)).get(companyId);
        if (!userId.equals(ownerId)) {
            throw new CompanyNotFoundException();
        }
    }

    private LegalForm findLegalForm(CompanyDTO company) {
        LegalForm legalForm = legalFormRepository.findByCode(company.getLegalForm())
                .orElseThrow(() -> new InvalidFieldException("legalForm", "Форма должна быть ООО или ИП"));
        if (company.getCompanyInn().length() != legalForm.getInnLength()) {
            throw new InvalidFieldException("companyInn",
                    "У " + legalForm.getCode() + " ИНН из " + legalForm.getInnLength() + " цифр");
        }
        return legalForm;
    }

    private void checkInnIsFree(CompanyDTO company) {
        String innCompanyId = companyRepository.findCompanyIdsByInn(Set.of(company.getCompanyInn()))
                .get(company.getCompanyInn());
        if (innCompanyId != null && !innCompanyId.equals(company.getCompanyId())) {
            throw new AlreadyExistsException("companyInn", "Этот ИНН уже указан у другой компании");
        }
    }
}
