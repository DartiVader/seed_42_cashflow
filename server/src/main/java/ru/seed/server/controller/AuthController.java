package ru.seed.server.controller;

import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import ru.seed.server.dto.AuthDTO;
import ru.seed.server.dto.LoginRequest;
import ru.seed.server.dto.RegisterRequest;
import ru.seed.server.exception.Response;
import ru.seed.server.service.AuthService;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public Response<AuthDTO> register(@Valid @RequestBody RegisterRequest request, HttpServletResponse response) {
        return authService.register(request, response);
    }

    @PostMapping("/login")
    public Response<AuthDTO> login(@Valid @RequestBody LoginRequest request, HttpServletResponse response) {
        return authService.login(request, response);
    }

    @PostMapping("/logout")
    public Response<Void> logout(HttpServletResponse response) {
        return authService.logout(response);
    }
}
