package ru.seed.server.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import ru.seed.server.client.LlmClient;
import ru.seed.server.client.MlClient;
import ru.seed.server.config.LlmProperties;
import ru.seed.server.config.MlProperties;
import ru.seed.server.dto.ExplainRequest;
import ru.seed.server.dto.ForecastRequest;
import ru.seed.server.exception.CompanyNotFoundException;
import ru.seed.server.exception.Response;
import ru.seed.server.exception.ServiceUnavailableException;
import ru.seed.server.repository.CompanyRepository;
import ru.seed.server.utils.ResponseUtils;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeoutException;

@Slf4j
@Service
@RequiredArgsConstructor
public class ForecastService {

    private static final int DEFAULT_HORIZON_DAYS = 30;
    private static final int MIN_LOOKBACK_DAYS = 3;
    private static final int MAX_LOOKBACK_DAYS = 30;

    private final CompanyRepository companyRepository;
    private final MlClient mlClient;
    private final LlmClient llmClient;
    private final MlProperties mlProperties;
    private final LlmProperties llmProperties;

    public Response<Map<String, Object>> forecast(Long userId, String companyId, ForecastRequest request) {
        checkOwner(userId, companyId);
        Map<String, Object> body = new HashMap<>();
        body.put("as_of", request.getAsOf().toString());
        body.put("horizon_days", request.getHorizonDays() == null ? DEFAULT_HORIZON_DAYS : request.getHorizonDays());
        body.put("threshold", request.getThreshold() == null ? 0 : request.getThreshold());
        body.put("events", request.getEvents() == null ? List.of() : request.getEvents());
        if (request.getScenario() != null && !request.getScenario().isEmpty()) {
            body.put("scenario", request.getScenario());
        }
        long startedAt = System.currentTimeMillis();
        Map<String, Object> forecast = mlClient.forecast(companyId, body)
                .timeout(mlProperties.getTimeout())
                .onErrorMap(TimeoutException.class,
                        exception -> new ServiceUnavailableException(MlClient.FORECAST_UNAVAILABLE_MESSAGE))
                .block();
        log.info("Forecast built, companyId={}, ms={}", companyId, System.currentTimeMillis() - startedAt);
        return ResponseUtils.responseSuccess("forecast", forecast);
    }

    public Response<Map<String, Object>> explain(Long userId, String companyId, ExplainRequest request) {
        checkOwner(userId, companyId);
        Map<String, Object> body = new HashMap<>();
        body.put("kind", request.getKind());
        body.put("forecast", request.getForecast());
        if (request.getBase() != null) {
            body.put("base", request.getBase());
        }
        if (request.getQuestion() != null && !request.getQuestion().isBlank()) {
            body.put("question", request.getQuestion().trim());
        }
        long startedAt = System.currentTimeMillis();
        Map<String, Object> explanation = llmClient.explain(body)
                .timeout(llmProperties.getTimeout())
                .onErrorMap(TimeoutException.class,
                        exception -> new ServiceUnavailableException("Объяснение сейчас недоступно"))
                .block();
        log.info("Explanation built, companyId={}, kind={}, ms={}", companyId, request.getKind(),
                System.currentTimeMillis() - startedAt);
        return ResponseUtils.responseSuccess("explain", explanation);
    }

    public Response<Map<String, Object>> planFact(Long userId, String companyId, LocalDate asOf, int lookbackDays) {
        checkOwner(userId, companyId);
        int days = Math.max(MIN_LOOKBACK_DAYS, Math.min(lookbackDays, MAX_LOOKBACK_DAYS));
        long startedAt = System.currentTimeMillis();
        Map<String, Object> planFact = mlClient.planFact(companyId, asOf, days)
                .timeout(mlProperties.getTimeout())
                .onErrorMap(TimeoutException.class,
                        exception -> new ServiceUnavailableException(MlClient.PLAN_FACT_UNAVAILABLE_MESSAGE))
                .block();
        log.info("Plan-fact built, companyId={}, ms={}", companyId, System.currentTimeMillis() - startedAt);
        return ResponseUtils.responseSuccess("planFact", planFact);
    }

    private void checkOwner(Long userId, String companyId) {
        Long ownerId = companyRepository.findOwnerIds(Set.of(companyId)).get(companyId);
        if (!userId.equals(ownerId)) {
            throw new CompanyNotFoundException();
        }
    }
}
