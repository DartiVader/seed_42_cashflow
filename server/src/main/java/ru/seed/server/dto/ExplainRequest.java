package ru.seed.server.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.Map;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class ExplainRequest {

    @NotBlank(message = "Укажите тип объяснения")
    @Pattern(regexp = "summary|gap|scenario|answer", message = "Неизвестный тип объяснения")
    private String kind;

    @NotNull(message = "Нужен прогноз")
    private Map<String, Object> forecast;

    private Map<String, Object> base;

    @Size(max = 300, message = "Вопрос — не длиннее 300 символов")
    private String question;
}
