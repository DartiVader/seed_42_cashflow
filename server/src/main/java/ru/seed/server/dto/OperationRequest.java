package ru.seed.server.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
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
public class OperationRequest {

    @NotBlank(message = "Укажите код компании")
    @Size(max = 10, message = "Код компании — не больше 10 символов")
    private String companyId;

    @NotBlank(message = "Укажите номер операции")
    @Size(max = 20, message = "Номер операции — не больше 20 символов")
    private String operationId;

    @NotNull(message = "Укажите дату")
    private LocalDate date;

    @NotNull(message = "Укажите сумму")
    @DecimalMin(value = "0.01", message = "Сумма должна быть больше нуля")
    @Digits(integer = 13, fraction = 2, message = "Сумма — не больше двух знаков после точки")
    private BigDecimal amount;

    @NotBlank(message = "Укажите направление: Поступление или Списание")
    private String direction;

    @Pattern(regexp = "^$|\\d{10}|\\d{12}", message = "ИНН контрагента — 10 или 12 цифр")
    private String counterpartyInn;

    @NotBlank(message = "Укажите контрагента")
    @Size(max = 255, message = "Название контрагента слишком длинное")
    private String counterpartyName;

    private String paymentPurpose;
}
