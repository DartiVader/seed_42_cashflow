package ru.seed.server.service;

import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.AuthDTO;
import ru.seed.server.dto.LoginRequest;
import ru.seed.server.dto.RegisterRequest;
import ru.seed.server.exception.Response;
import ru.seed.server.mapper.UserMapper;
import ru.seed.server.model.User;
import ru.seed.server.security.AuthCookieService;
import ru.seed.server.security.TokenService;
import ru.seed.server.security.UserPrincipal;
import ru.seed.server.utils.EmailUtils;
import ru.seed.server.utils.ResponseUtils;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserService userService;
    private final AuthenticationManager authenticationManager;
    private final TokenService tokenService;
    private final AuthCookieService authCookieService;
    private final UserMapper userMapper;

    @Transactional
    public Response<AuthDTO> register(RegisterRequest request, HttpServletResponse response) {
        User user = userService.create(request.getEmail(), request.getPassword(), false);
        UserPrincipal principal = new UserPrincipal(user);
        Authentication authentication = UsernamePasswordAuthenticationToken.authenticated(
                principal, null, principal.getAuthorities());
        return ResponseUtils.responseSuccess("register", issueToken(authentication, response));
    }

    public Response<AuthDTO> login(LoginRequest request, HttpServletResponse response) {
        Authentication authentication = authenticationManager.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(
                        EmailUtils.normalize(request.getEmail()), request.getPassword()));
        AuthDTO authDto = issueToken(authentication, response);
        log.info("User logged in, userId={}", authDto.getUser().getId());
        return ResponseUtils.responseSuccess("login", authDto);
    }

    public Response<Void> logout(HttpServletResponse response) {
        response.addHeader(HttpHeaders.SET_COOKIE, authCookieService.clear().toString());
        return ResponseUtils.responseSuccess("logout", null);
    }

    private AuthDTO issueToken(Authentication authentication, HttpServletResponse response) {
        Jwt jwt = tokenService.generate(authentication);
        response.addHeader(HttpHeaders.SET_COOKIE, authCookieService.create(jwt).toString());
        UserPrincipal principal = (UserPrincipal) authentication.getPrincipal();
        return new AuthDTO(jwt.getExpiresAt(), userMapper.toDto(principal.getUser()));
    }
}
