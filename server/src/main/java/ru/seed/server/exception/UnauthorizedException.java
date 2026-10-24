package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class UnauthorizedException extends ValidationException {

    public UnauthorizedException(String message) {
        super(HttpStatus.UNAUTHORIZED, message);
    }
}
