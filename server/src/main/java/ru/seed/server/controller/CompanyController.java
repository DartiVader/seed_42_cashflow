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
import ru.seed.server.dto.CompanyDTO;
import ru.seed.server.dto.CompanyRequest;
import ru.seed.server.dto.PageDTO;
import ru.seed.server.exception.Response;
import ru.seed.server.service.CompanyService;

@RestController
@RequestMapping("/api/companies")
@RequiredArgsConstructor
public class CompanyController {

    private final CompanyService companyService;

    @GetMapping
    public Response<PageDTO<CompanyDTO>> getCompanies(@AuthenticationPrincipal Jwt jwt,
                                                      @RequestParam(defaultValue = "0") int page,
                                                      @RequestParam(defaultValue = "50") int size) {
        return companyService.getCompanies(Long.valueOf(jwt.getSubject()), page, size);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Response<CompanyDTO> createCompany(@AuthenticationPrincipal Jwt jwt,
                                              @Valid @RequestBody CompanyRequest request) {
        return companyService.createCompany(Long.valueOf(jwt.getSubject()), request);
    }

    @PutMapping("/{companyId}")
    public Response<CompanyDTO> updateCompany(@AuthenticationPrincipal Jwt jwt, @PathVariable String companyId,
                                              @Valid @RequestBody CompanyRequest request) {
        return companyService.updateCompany(Long.valueOf(jwt.getSubject()), companyId, request);
    }

    @DeleteMapping("/{companyId}")
    public Response<Void> deleteCompany(@AuthenticationPrincipal Jwt jwt, @PathVariable String companyId) {
        return companyService.deleteCompany(Long.valueOf(jwt.getSubject()), companyId);
    }
}
