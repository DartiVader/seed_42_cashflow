package ru.seed.server.exception;

import lombok.Getter;
import org.springframework.http.HttpStatusCode;

@Getter
public class WebCustomClientException extends RuntimeException {

    private final HttpStatusCode statusCode;
    private final String responseBody;
    private final String unavailableMessage;

    public WebCustomClientException(HttpStatusCode statusCode, String responseBody, String unavailableMessage) {
        super("External service responded with status " + statusCode.value());
        this.statusCode = statusCode;
        this.responseBody = responseBody;
        this.unavailableMessage = unavailableMessage;
    }
}
