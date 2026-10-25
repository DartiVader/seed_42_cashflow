package ru.seed.server.utils;

import ru.seed.server.dto.ImportErrorDTO;
import ru.seed.server.dto.ImportReportDTO;

public final class ImportReportUtils {

    public static final int MAX_ERRORS = 100;

    private ImportReportUtils() {
    }

    public static void accept(ImportReportDTO report, int count) {
        report.setAccepted(report.getAccepted() + count);
    }

    public static void skip(ImportReportDTO report) {
        report.setSkipped(report.getSkipped() + 1);
    }

    public static void reject(ImportReportDTO report, int lineNumber, String message) {
        report.setRejected(report.getRejected() + 1);
        if (report.getErrors().size() < MAX_ERRORS) {
            report.getErrors().add(new ImportErrorDTO(lineNumber, message));
        }
    }

    public static void merge(ImportReportDTO target, ImportReportDTO source) {
        target.setAccepted(target.getAccepted() + source.getAccepted());
        target.setSkipped(target.getSkipped() + source.getSkipped());
        target.setRejected(target.getRejected() + source.getRejected());
        for (ImportErrorDTO error : source.getErrors()) {
            if (target.getErrors().size() < MAX_ERRORS) {
                target.getErrors().add(error);
            }
        }
    }
}
