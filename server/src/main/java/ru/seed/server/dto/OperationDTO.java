package ru.seed.server.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class OperationDTO {
    private Long id;
    private String companyId;
    private String operationId;
    private LocalDate date;
    private BigDecimal amount;
    private String direction;
    private String counterpartyInn;
    private String counterpartyName;
    private String paymentPurpose;
}
