package ru.seed.server.exception;

import org.springframework.http.HttpStatus;

public class ServerInternalException extends ValidationException {

    public ServerInternalException(String message) {
        super(HttpStatus.INTERNAL_SERVER_ERROR, message);
    }
}
