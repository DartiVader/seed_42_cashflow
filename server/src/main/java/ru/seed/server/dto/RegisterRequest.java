package ru.seed.server.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class RegisterRequest {

    @NotBlank(message = "Укажите email")
    @Email(regexp = ".+@.+\\.\\p{L}{2,}", message = "Проверьте email, похоже, в нём опечатка")
    @Size(max = 255, message = "Email слишком длинный")
    private String email;

    @NotBlank(message = "Придумайте пароль")
    @Size(min = 8, max = 72, message = "Пароль должен быть от 8 до 72 символов")
    private String password;
}
