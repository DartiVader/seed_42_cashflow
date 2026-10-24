package ru.seed.server.utils;

import ru.seed.server.dto.ErrorDTO;
import ru.seed.server.exception.Response;
import ru.seed.server.exception.ValidationException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

public final class ResponseUtils {

    private ResponseUtils() {
    }

    public static <T> Response<T> responseSuccess(String methodName, T data) {
        return new Response<>(LocalDateTime.now(), methodName, true, data, List.of());
    }

    public static <T> Response<T> responseError(String methodName, ValidationException error) {
        return responseError(methodName, List.of(error));
    }

    public static <T> Response<T> responseError(String methodName, List<? extends ValidationException> errors) {
        List<ErrorDTO> listErrors = new ArrayList<>();
        for (ValidationException error : errors) {
            listErrors.add(new ErrorDTO(error.getField(), error.getMessage()));
        }
        return new Response<>(LocalDateTime.now(), methodName, false, null, listErrors);
    }
}
