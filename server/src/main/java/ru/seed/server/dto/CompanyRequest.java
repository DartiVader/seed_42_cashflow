package ru.seed.server.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class CompanyRequest {

    @NotBlank(message = "Укажите код компании")
    @Size(max = 10, message = "Код компании — не больше 10 символов")
    private String companyId;

    @NotBlank(message = "Укажите название компании")
    @Size(max = 255, message = "Название слишком длинное")
    private String companyName;

    @NotBlank(message = "Укажите ИНН компании")
    @Pattern(regexp = "\\d{10}|\\d{12}", message = "ИНН — 10 цифр для ООО или 12 для ИП")
    private String companyInn;

    @NotBlank(message = "Укажите форму: ООО или ИП")
    private String legalForm;

    @NotBlank(message = "Укажите вид деятельности")
    @Size(max = 100, message = "Вид деятельности — не больше 100 символов")
    private String industry;
}
