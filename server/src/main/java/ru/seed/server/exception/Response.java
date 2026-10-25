package ru.seed.server.exception;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import ru.seed.server.dto.ErrorDTO;

import java.time.LocalDateTime;
import java.util.List;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
public class Response<T> {

    private LocalDateTime localDateTime;
    private String methodName;
    private boolean success;
    private T data;
    private List<ErrorDTO> listErrors;
}
