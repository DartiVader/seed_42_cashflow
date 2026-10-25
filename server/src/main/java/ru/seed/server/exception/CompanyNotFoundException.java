package ru.seed.server.exception;

public class CompanyNotFoundException extends NotFoundException {

    public CompanyNotFoundException() {
        super("Компания не найдена");
    }
}
