package ru.seed.server.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class CompanyFilter {
    private String companyId;
    private String companyName;
    private String companyInn;
    private String legalForm;
    private String industry;
    private String sortField;
    private String sortDirection;
}
