package ru.seed.server.controller;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import ru.seed.server.dto.OperationDTO;
import ru.seed.server.dto.OperationRequest;
import ru.seed.server.dto.PageDTO;
import ru.seed.server.exception.Response;
import ru.seed.server.service.OperationService;

@RestController
@RequestMapping("/api/operations")
@RequiredArgsConstructor
public class OperationController {

    private final OperationService operationService;

    @GetMapping
    public Response<PageDTO<OperationDTO>> getOperations(@AuthenticationPrincipal Jwt jwt,
                                                         @RequestParam(required = false) String companyId,
                                                         @RequestParam(defaultValue = "0") int page,
                                                         @RequestParam(defaultValue = "50") int size) {
        return operationService.getOperations(Long.valueOf(jwt.getSubject()), companyId, page, size);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Response<OperationDTO> createOperation(@AuthenticationPrincipal Jwt jwt,
                                                  @Valid @RequestBody OperationRequest request) {
        return operationService.createOperation(Long.valueOf(jwt.getSubject()), request);
    }

    @PutMapping("/{id}")
    public Response<OperationDTO> updateOperation(@AuthenticationPrincipal Jwt jwt, @PathVariable Long id,
                                                  @Valid @RequestBody OperationRequest request) {
        return operationService.updateOperation(Long.valueOf(jwt.getSubject()), id, request);
    }

    @DeleteMapping("/{id}")
    public Response<Void> deleteOperation(@AuthenticationPrincipal Jwt jwt, @PathVariable Long id) {
        return operationService.deleteOperation(Long.valueOf(jwt.getSubject()), id);
    }
}
