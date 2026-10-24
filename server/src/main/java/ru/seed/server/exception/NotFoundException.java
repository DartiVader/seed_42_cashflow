package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class NotFoundException extends ValidationException {

    public NotFoundException(String message) {
        super(HttpStatus.NOT_FOUND, message);
    }
}
