package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class CsvFormatException extends ValidationException {

    public CsvFormatException(String message) {
        super(HttpStatus.BAD_REQUEST, message);
    }
}
