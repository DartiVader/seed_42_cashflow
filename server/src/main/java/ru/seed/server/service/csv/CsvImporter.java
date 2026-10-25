package ru.seed.server.service.csv;

import ru.seed.server.dto.CsvRow;
import ru.seed.server.dto.ImportFileType;
import ru.seed.server.dto.ImportReportDTO;

import java.util.List;

public interface CsvImporter<R extends CsvRow> {

    ImportFileType getFileType();

    List<String> getHeader();

    R parse(String line, int lineNumber);

    void saveBatch(Long userId, List<R> rows, ImportReportDTO report);
}
