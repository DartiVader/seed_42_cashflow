package ru.seed.server.exception;

public class OperationNotFoundException extends NotFoundException {

    public OperationNotFoundException() {
        super("Операция не найдена");
    }
}
