package ru.seed.server.service.csv;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.ImportFileType;
import ru.seed.server.dto.ImportReportDTO;
import ru.seed.server.dto.OperationCsvRow;
import ru.seed.server.exception.CsvFormatException;
import ru.seed.server.model.Direction;
import ru.seed.server.repository.CompanyRepository;
import ru.seed.server.repository.CounterpartyRepository;
import ru.seed.server.repository.DirectionRepository;
import ru.seed.server.repository.OperationRepository;
import ru.seed.server.utils.CsvUtils;
import ru.seed.server.utils.ImportReportUtils;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class OperationCsvImporter implements CsvImporter<OperationCsvRow> {

    private static final List<String> HEADER = List.of("company_id", "operation_id", "operation_date", "amount",
            "direction", "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod");

    private final CompanyRepository companyRepository;
    private final CounterpartyRepository counterpartyRepository;
    private final DirectionRepository directionRepository;
    private final OperationRepository operationRepository;

    @Override
    public ImportFileType getFileType() {
        return ImportFileType.OPERATIONS;
    }

    @Override
    public List<String> getHeader() {
        return HEADER;
    }

    @Override
    public OperationCsvRow parse(String line, int lineNumber) {
        String[] values = CsvUtils.split(line);
        if (values.length < HEADER.size()) {
            throw new CsvFormatException("Ожидалось " + HEADER.size() + " колонок, а в строке " + values.length);
        }
        OperationCsvRow row = new OperationCsvRow();
        row.setLineNumber(lineNumber);
        row.setCompanyId(CsvUtils.required(values[0], "company_id", 10));
        row.setSourceOperationId(CsvUtils.required(values[1], "operation_id", 20));
        if (!row.getSourceOperationId().startsWith(row.getCompanyId() + "-")) {
            throw new CsvFormatException("Номер операции " + row.getSourceOperationId()
                    + " не относится к компании " + row.getCompanyId());
        }
        row.setDate(CsvUtils.parseDate(values[2]));
        row.setAmount(CsvUtils.parseAmount(values[3]));
        row.setDirection(CsvUtils.required(values[4], "direction", 50));
        row.setCounterpartyInn(CsvUtils.normalizeInn(values[5]));
        row.setCounterpartyName(CsvUtils.required(values[6], "counterparty_name", 255));
        row.setPaymentPurpose(CsvUtils.optional(CsvUtils.join(values, 7, values.length - 1)));
        return row;
    }

    @Override
    @Transactional
    public void saveBatch(Long userId, List<OperationCsvRow> rows, ImportReportDTO report) {
        Map<String, Short> directionIds = new HashMap<>();
        for (Direction direction : directionRepository.findAll()) {
            directionIds.put(direction.getName(), direction.getId());
        }

        Set<String> companyIds = new HashSet<>();
        Set<String> sourceOperationIds = new HashSet<>();
        for (OperationCsvRow row : rows) {
            companyIds.add(row.getCompanyId());
            sourceOperationIds.add(row.getSourceOperationId());
        }
        Map<String, Long> ownerIds = companyRepository.findOwnerIds(companyIds);
        Set<String> existingIds = operationRepository.findExistingSourceIds(sourceOperationIds);

        List<OperationCsvRow> newRows = new ArrayList<>();
        for (OperationCsvRow row : rows) {
            Short directionId = directionIds.get(row.getDirection());
            if (!userId.equals(ownerIds.get(row.getCompanyId()))) {
                ImportReportUtils.reject(report, row.getLineNumber(), "Компании " + row.getCompanyId()
                        + " нет среди ваших — сначала загрузите справочник компаний");
                continue;
            }
            if (directionId == null) {
                ImportReportUtils.reject(report, row.getLineNumber(),
                        "Направление должно быть «Поступление» или «Списание»");
                continue;
            }
            if (existingIds.contains(row.getSourceOperationId())) {
                ImportReportUtils.skip(report);
                continue;
            }
            existingIds.add(row.getSourceOperationId());
            row.setDirectionId(directionId);
            newRows.add(row);
        }

        fillCounterpartyIds(newRows);
        operationRepository.insertAll(newRows);
        ImportReportUtils.accept(report, newRows.size());
    }

    private void fillCounterpartyIds(List<OperationCsvRow> rows) {
        Set<String> inns = new HashSet<>();
        Set<String> names = new HashSet<>();
        for (OperationCsvRow row : rows) {
            if (row.getCounterpartyInn() != null) {
                inns.add(row.getCounterpartyInn());
            } else {
                names.add(row.getCounterpartyName());
            }
        }
        Map<String, Long> idsByInn = counterpartyRepository.findIdsByInn(inns);
        Map<String, Long> idsByName = counterpartyRepository.findIdsByNameWithoutInn(names);

        for (OperationCsvRow row : rows) {
            String inn = row.getCounterpartyInn();
            String name = row.getCounterpartyName();
            if (inn != null) {
                if (!idsByInn.containsKey(inn)) {
                    idsByInn.put(inn, counterpartyRepository.insert(inn, name));
                }
                row.setCounterpartyId(idsByInn.get(inn));
            } else {
                if (!idsByName.containsKey(name)) {
                    idsByName.put(name, counterpartyRepository.insert(null, name));
                }
                row.setCounterpartyId(idsByName.get(name));
            }
        }
    }
}
