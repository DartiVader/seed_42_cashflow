package ru.seed.server.security;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.oauth2.server.resource.web.BearerTokenResolver;
import org.springframework.security.oauth2.server.resource.web.DefaultBearerTokenResolver;
import org.springframework.web.util.WebUtils;

public class CookieBearerTokenResolver implements BearerTokenResolver {

    private static final String AUTH_PATH_PREFIX = "/api/auth/";

    private final DefaultBearerTokenResolver headerTokenResolver = new DefaultBearerTokenResolver();

    @Override
    public String resolve(HttpServletRequest request) {
        if (request.getRequestURI().startsWith(AUTH_PATH_PREFIX)) {
            return null;
        }
        Cookie cookie = WebUtils.getCookie(request, AuthCookieService.ACCESS_TOKEN_COOKIE);
        if (cookie != null) {
            return cookie.getValue();
        }
        return headerTokenResolver.resolve(request);
    }
}
