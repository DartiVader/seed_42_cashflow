package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class ServiceUnavailableException extends ValidationException {

    public ServiceUnavailableException(String message) {
        super(HttpStatus.SERVICE_UNAVAILABLE, message);
    }
}
