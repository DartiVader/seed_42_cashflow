package ru.seed.server.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.format.annotation.DateTimeFormat;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class OperationFilter {
    private String companyId;
    private String operationId;
    private String counterpartyName;
    private String counterpartyInn;
    private String paymentPurpose;
    private String direction;
    private BigDecimal amountFrom;
    private BigDecimal amountTo;

    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
    private LocalDate dateFrom;

    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
    private LocalDate dateTo;

    private String sortField;
    private String sortDirection;
}
