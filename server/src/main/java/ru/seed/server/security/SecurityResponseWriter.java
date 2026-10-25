package ru.seed.server.security;

import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import ru.seed.server.exception.Response;
import ru.seed.server.exception.ValidationException;
import ru.seed.server.utils.ResponseUtils;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

@Component
@RequiredArgsConstructor
public class SecurityResponseWriter {

    private final ObjectMapper objectMapper;

    public void write(HttpServletResponse response, String methodName, ValidationException error) throws IOException {
        HttpStatus status = error.getHttpStatus();
        Response<Void> body = ResponseUtils.responseError(methodName, error);

        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getOutputStream(), body);
    }
}
