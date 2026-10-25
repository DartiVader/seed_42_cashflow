package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class AlreadyExistsException extends ValidationException {

    public AlreadyExistsException(String field, String message) {
        super(HttpStatus.CONFLICT, field, message);
    }
}
