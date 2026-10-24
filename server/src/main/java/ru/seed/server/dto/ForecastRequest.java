package ru.seed.server.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ForecastRequest {

    @NotNull(message = "Укажите дату прогноза")
    private LocalDate asOf;

    @Min(value = 7, message = "Горизонт — от 7 дней")
    @Max(value = 90, message = "Горизонт — не больше 90 дней")
    private Integer horizonDays = 30;

    @Min(value = 0, message = "Порог не может быть отрицательным")
    private Long threshold = 0L;

    private List<Map<String, Object>> events = List.of();

    private Map<String, Object> scenario;
}
