package ru.seed.server.dto;

import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@Setter
@NoArgsConstructor
public class OperationCsvRow extends CsvRow {
    private String companyId;
    private String sourceOperationId;
    private LocalDate date;
    private BigDecimal amount;
    private String direction;
    private String counterpartyInn;
    private String counterpartyName;
    private String paymentPurpose;
    private Short directionId;
    private Long counterpartyId;
}
