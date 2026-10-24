package ru.seed.server.exception;

import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import ru.seed.server.utils.ExternalErrorUtils;
import ru.seed.server.utils.ResponseUtils;

import java.util.ArrayList;
import java.util.List;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ValidationException.class)
    public ResponseEntity<Response<Void>> handleValidationException(ValidationException exception,
                                                                    HttpServletRequest request) {
        return ResponseEntity.status(exception.getHttpStatus())
                .body(ResponseUtils.responseError(methodName(request), exception));
    }

    @ExceptionHandler(WebCustomClientException.class)
    public ResponseEntity<Response<Void>> handleWebCustomClientException(WebCustomClientException exception,
                                                                         HttpServletRequest request) {
        log.warn("External service error, status={}", exception.getStatusCode().value());
        if (exception.getStatusCode().is4xxClientError()) {
            String message = ExternalErrorUtils.extractMessage(exception.getResponseBody(),
                    "Не удалось построить прогноз по этой выписке");
            return ResponseEntity.status(exception.getStatusCode())
                    .body(ResponseUtils.responseError(methodName(request), new BadRequestException(message)));
        }
        return handleValidationException(new ServiceUnavailableException(exception.getUnavailableMessage()), request);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Response<Void>> handleMethodArgumentNotValidException(MethodArgumentNotValidException exception,
                                                                                HttpServletRequest request) {
        List<InvalidFieldException> errors = new ArrayList<>();
        for (FieldError fieldError : exception.getBindingResult().getFieldErrors()) {
            errors.add(new InvalidFieldException(fieldError.getField(), fieldError.getDefaultMessage()));
        }
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ResponseUtils.responseError(methodName(request), errors));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Response<Void>> handleHttpMessageNotReadableException(HttpMessageNotReadableException exception,
                                                                                HttpServletRequest request) {
        return handleValidationException(new BadRequestException("Не удалось прочитать данные запроса"), request);
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Response<Void>> handleMissingServletRequestParameterException(MissingServletRequestParameterException exception,
                                                                                        HttpServletRequest request) {
        return handleValidationException(
                new InvalidFieldException(exception.getParameterName(), "Не указан параметр " + exception.getParameterName()), request);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<Response<Void>> handleMethodArgumentTypeMismatchException(MethodArgumentTypeMismatchException exception,
                                                                                    HttpServletRequest request) {
        return handleValidationException(
                new InvalidFieldException(exception.getName(), "Неверное значение параметра " + exception.getName()), request);
    }

    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<Response<Void>> handleAuthenticationException(AuthenticationException exception,
                                                                        HttpServletRequest request) {
        log.warn("Failed authentication: {}", exception.getClass().getSimpleName());
        return handleValidationException(new UnauthorizedException("Неверный email или пароль"), request);
    }

    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<Response<Void>> handleAccessDeniedException(AccessDeniedException exception,
                                                                      HttpServletRequest request) {
        return handleValidationException(new ForbiddenException("Недостаточно прав для этого действия"), request);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Response<Void>> handleNoResourceFoundException(NoResourceFoundException exception,
                                                                         HttpServletRequest request) {
        return handleValidationException(new NotFoundException("Такой страницы нет"), request);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<Response<Void>> handleHttpRequestMethodNotSupportedException(HttpRequestMethodNotSupportedException exception,
                                                                                       HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED)
                .body(ResponseUtils.responseError(methodName(request),
                        new BadRequestException("Этот метод запроса не поддерживается")));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Response<Void>> handleMaxUploadSizeExceededException(MaxUploadSizeExceededException exception,
                                                                               HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.CONTENT_TOO_LARGE)
                .body(ResponseUtils.responseError(methodName(request),
                        new BadRequestException("Файл больше 100 МБ, разделите его на части")));
    }

    @ExceptionHandler(MissingServletRequestPartException.class)
    public ResponseEntity<Response<Void>> handleMissingServletRequestPartException(MissingServletRequestPartException exception,
                                                                                   HttpServletRequest request) {
        return handleValidationException(new BadRequestException("Выберите файл для загрузки"), request);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Response<Void>> handleException(Exception exception, HttpServletRequest request) {
        log.error("Unhandled exception", exception);
        return handleValidationException(new ServerInternalException("Что-то пошло не так, попробуйте ещё раз"), request);
    }

    private String methodName(HttpServletRequest request) {
        Object handler = request.getAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE);
        if (handler instanceof HandlerMethod handlerMethod) {
            return handlerMethod.getMethod().getName();
        }
        return "unknown";
    }
}
