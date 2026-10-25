package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class BadRequestException extends ValidationException {

    public BadRequestException(String message) {
        super(HttpStatus.BAD_REQUEST, message);
    }
}
