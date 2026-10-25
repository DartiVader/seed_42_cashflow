package ru.seed.server.service.csv;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.CompanyCsvRow;
import ru.seed.server.dto.ImportFileType;
import ru.seed.server.dto.ImportReportDTO;
import ru.seed.server.exception.CsvFormatException;
import ru.seed.server.model.LegalForm;
import ru.seed.server.repository.CompanyRepository;
import ru.seed.server.repository.LegalFormRepository;
import ru.seed.server.utils.CsvUtils;
import ru.seed.server.utils.ImportReportUtils;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class CompanyCsvImporter implements CsvImporter<CompanyCsvRow> {

    private static final List<String> HEADER = List.of("company_id", "company_name", "company_inn", "legal_form",
            "industry", "first_operation_date", "last_operation_date", "operations_count");

    private final CompanyRepository companyRepository;
    private final LegalFormRepository legalFormRepository;

    @Override
    public ImportFileType getFileType() {
        return ImportFileType.COMPANIES;
    }

    @Override
    public List<String> getHeader() {
        return HEADER;
    }

    @Override
    public CompanyCsvRow parse(String line, int lineNumber) {
        String[] values = CsvUtils.split(line);
        if (values.length != HEADER.size()) {
            throw new CsvFormatException("Ожидалось " + HEADER.size() + " колонок, а в строке " + values.length);
        }
        CompanyCsvRow row = new CompanyCsvRow();
        row.setLineNumber(lineNumber);
        row.setCompanyId(CsvUtils.required(values[0], "company_id", 10));
        row.setCompanyName(CsvUtils.required(values[1], "company_name", 255));
        row.setCompanyInn(CsvUtils.normalizeInn(CsvUtils.required(values[2], "company_inn", 12)));
        row.setLegalForm(CsvUtils.required(values[3], "legal_form", 10));
        row.setIndustry(CsvUtils.required(values[4], "industry", 100));
        return row;
    }

    @Override
    @Transactional
    public void saveBatch(Long userId, List<CompanyCsvRow> rows, ImportReportDTO report) {
        Map<String, LegalForm> legalForms = new HashMap<>();
        for (LegalForm legalForm : legalFormRepository.findAll()) {
            legalForms.put(legalForm.getCode(), legalForm);
        }

        Set<String> companyIds = new HashSet<>();
        Set<String> inns = new HashSet<>();
        for (CompanyCsvRow row : rows) {
            companyIds.add(row.getCompanyId());
            inns.add(row.getCompanyInn());
        }
        Map<String, Long> ownerIds = companyRepository.findOwnerIds(companyIds);
        Map<String, String> companyIdsByInn = companyRepository.findCompanyIdsByInn(inns);

        for (CompanyCsvRow row : rows) {
            LegalForm legalForm = legalForms.get(row.getLegalForm());
            Long ownerId = ownerIds.get(row.getCompanyId());
            String innCompanyId = companyIdsByInn.get(row.getCompanyInn());

            if (legalForm == null) {
                ImportReportUtils.reject(report, row.getLineNumber(), "Форма должна быть ООО или ИП");
                continue;
            }
            if (row.getCompanyInn().length() != legalForm.getInnLength()) {
                ImportReportUtils.reject(report, row.getLineNumber(),
                        "У " + legalForm.getCode() + " ИНН из " + legalForm.getInnLength() + " цифр");
                continue;
            }
            if (ownerId != null && !ownerId.equals(userId)) {
                ImportReportUtils.reject(report, row.getLineNumber(),
                        "Компания " + row.getCompanyId() + " уже зарегистрирована другим пользователем");
                continue;
            }
            if (innCompanyId != null && !innCompanyId.equals(row.getCompanyId())) {
                ImportReportUtils.reject(report, row.getLineNumber(),
                        "Этот ИНН уже указан у компании " + innCompanyId);
                continue;
            }

            if (ownerId == null) {
                companyRepository.insert(row.getCompanyId(), userId, row.getCompanyName(), row.getCompanyInn(),
                        legalForm.getId(), row.getIndustry());
            } else {
                companyRepository.update(row.getCompanyId(), row.getCompanyName(), row.getCompanyInn(),
                        legalForm.getId(), row.getIndustry());
            }
            ownerIds.put(row.getCompanyId(), userId);
            companyIdsByInn.put(row.getCompanyInn(), row.getCompanyId());
            ImportReportUtils.accept(report, 1);
        }
    }
}
