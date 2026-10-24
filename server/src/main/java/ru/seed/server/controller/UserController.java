package ru.seed.server.controller;

import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import ru.seed.server.dto.UserDTO;
import ru.seed.server.exception.Response;
import ru.seed.server.service.UserService;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @GetMapping("/me")
    public Response<UserDTO> getCurrentUser(@AuthenticationPrincipal Jwt jwt) {
        return userService.getCurrentUser(Long.valueOf(jwt.getSubject()));
    }
}
