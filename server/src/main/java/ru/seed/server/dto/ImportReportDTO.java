package ru.seed.server.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
public class ImportReportDTO {
    private ImportFileType fileType;
    private int total;
    private int accepted;
    private int skipped;
    private int rejected;
    private List<ImportErrorDTO> errors = new ArrayList<>();
}
