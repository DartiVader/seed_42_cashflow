package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class ForbiddenException extends ValidationException {

    public ForbiddenException(String message) {
        super(HttpStatus.FORBIDDEN, message);
    }
}
