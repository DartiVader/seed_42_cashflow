package ru.seed.server.service.csv;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import ru.seed.server.dto.CsvRow;
import ru.seed.server.dto.ImportReportDTO;
import ru.seed.server.exception.CsvFormatException;
import ru.seed.server.exception.Response;
import ru.seed.server.utils.CsvUtils;
import ru.seed.server.utils.ImportReportUtils;
import ru.seed.server.utils.ResponseUtils;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class CsvImportService {

    private static final int BATCH_SIZE = 1000;

    private final List<CsvImporter<?>> importers;

    public Response<ImportReportDTO> importFile(Long userId, MultipartFile file) {
        if (file.isEmpty()) {
            throw new CsvFormatException("Файл пустой");
        }
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8))) {
            String header = reader.readLine();
            if (header == null) {
                throw new CsvFormatException("Файл пустой");
            }
            CsvImporter<?> importer = findImporter(CsvUtils.splitHeader(header));
            long startedAt = System.currentTimeMillis();
            ImportReportDTO report = importRows(userId, importer, reader);
            log.info("CSV imported, userId={}, fileType={}, total={}, accepted={}, skipped={}, rejected={}, ms={}",
                    userId, report.getFileType(), report.getTotal(), report.getAccepted(), report.getSkipped(),
                    report.getRejected(), System.currentTimeMillis() - startedAt);
            return ResponseUtils.responseSuccess("importFile", report);
        } catch (IOException exception) {
            throw new CsvFormatException("Не удалось прочитать файл, попробуйте загрузить его ещё раз");
        }
    }

    private CsvImporter<?> findImporter(List<String> header) {
        for (CsvImporter<?> importer : importers) {
            if (importer.getHeader().equals(header)) {
                return importer;
            }
        }
        throw new CsvFormatException("Не удалось распознать файл: нужна выписка операций или справочник компаний "
                + "с разделителем «;» и строкой заголовков, как в исходном файле");
    }

    private <R extends CsvRow> ImportReportDTO importRows(Long userId, CsvImporter<R> importer,
                                                          BufferedReader reader) throws IOException {
        ImportReportDTO report = new ImportReportDTO();
        report.setFileType(importer.getFileType());
        List<R> batch = new ArrayList<>();
        int lineNumber = 1;
        String line = reader.readLine();
        while (line != null) {
            lineNumber++;
            if (!line.isBlank()) {
                report.setTotal(report.getTotal() + 1);
                try {
                    batch.add(importer.parse(line, lineNumber));
                } catch (CsvFormatException exception) {
                    ImportReportUtils.reject(report, lineNumber, exception.getMessage());
                }
            }
            if (batch.size() == BATCH_SIZE) {
                saveBatch(userId, importer, batch, report);
                batch = new ArrayList<>();
            }
            line = reader.readLine();
        }
        if (!batch.isEmpty()) {
            saveBatch(userId, importer, batch, report);
        }
        return report;
    }

    private <R extends CsvRow> void saveBatch(Long userId, CsvImporter<R> importer, List<R> batch,
                                              ImportReportDTO report) {
        ImportReportDTO batchReport = new ImportReportDTO();
        try {
            importer.saveBatch(userId, batch, batchReport);
            ImportReportUtils.merge(report, batchReport);
        } catch (DataAccessException exception) {
            log.warn("CSV batch failed, userId={}, firstLine={}, error={}",
                    userId, batch.get(0).getLineNumber(), exception.getClass().getSimpleName());
            for (R row : batch) {
                ImportReportUtils.reject(report, row.getLineNumber(), "Строку не удалось сохранить, проверьте данные");
            }
        }
    }
}
