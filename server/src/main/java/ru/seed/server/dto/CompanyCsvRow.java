package ru.seed.server.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
public class CompanyCsvRow extends CsvRow {
    private String companyId;
    private String companyName;
    private String companyInn;
    private String legalForm;
    private String industry;
}
