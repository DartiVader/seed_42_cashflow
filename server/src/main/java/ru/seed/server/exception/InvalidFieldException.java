package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class InvalidFieldException extends ValidationException {

    public InvalidFieldException(String field, String message) {
        super(HttpStatus.BAD_REQUEST, field, message);
    }
}
