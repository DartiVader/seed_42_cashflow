package ru.seed.server.controller;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import ru.seed.server.dto.ExplainRequest;
import ru.seed.server.dto.ForecastRequest;
import ru.seed.server.exception.Response;
import ru.seed.server.service.ForecastService;

import java.time.LocalDate;
import java.util.Map;

@RestController
@RequestMapping("/api/companies/{companyId}")
@RequiredArgsConstructor
public class ForecastController {

    private final ForecastService forecastService;

    @PostMapping("/forecast")
    public Response<Map<String, Object>> forecast(@AuthenticationPrincipal Jwt jwt, @PathVariable String companyId,
                                                  @Valid @RequestBody ForecastRequest request) {
        return forecastService.forecast(Long.valueOf(jwt.getSubject()), companyId, request);
    }

    @PostMapping("/explain")
    public Response<Map<String, Object>> explain(@AuthenticationPrincipal Jwt jwt, @PathVariable String companyId,
                                                 @Valid @RequestBody ExplainRequest request) {
        return forecastService.explain(Long.valueOf(jwt.getSubject()), companyId, request);
    }

    @GetMapping("/plan-fact")
    public Response<Map<String, Object>> planFact(@AuthenticationPrincipal Jwt jwt, @PathVariable String companyId,
                                                  @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate asOf,
                                                  @RequestParam(defaultValue = "10") int lookbackDays) {
        return forecastService.planFact(Long.valueOf(jwt.getSubject()), companyId, asOf, lookbackDays);
    }
}
