package ru.seed.server.exception;

public class UserNotFoundException extends NotFoundException {

    public UserNotFoundException() {
        super("Пользователь не найден");
    }
}
