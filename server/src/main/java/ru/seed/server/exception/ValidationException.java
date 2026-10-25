package ru.seed.server.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

@Getter
public abstract class ValidationException extends RuntimeException {

    private final HttpStatus httpStatus;
    private final String field;

    protected ValidationException(HttpStatus httpStatus, String message) {
        this(httpStatus, null, message);
    }

    protected ValidationException(HttpStatus httpStatus, String field, String message) {
        super(message);
        this.httpStatus = httpStatus;
        this.field = field;
    }
}
