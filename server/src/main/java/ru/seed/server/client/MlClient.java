package ru.seed.server.client;

import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import ru.seed.server.exception.ServiceUnavailableException;
import ru.seed.server.exception.WebCustomClientException;
import ru.seed.server.security.RequestIdFilter;

import java.time.LocalDate;
import java.util.Map;

@Component
public class MlClient {

    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE = new ParameterizedTypeReference<>() {
    };

    public static final String FORECAST_UNAVAILABLE_MESSAGE = "Сервис прогноза сейчас недоступен, попробуйте через минуту";
    public static final String PLAN_FACT_UNAVAILABLE_MESSAGE = "Сверка с фактом сейчас недоступна";

    private final WebClient mlWebClient;

    public MlClient(@Qualifier("mlWebClient") WebClient mlWebClient) {
        this.mlWebClient = mlWebClient;
    }

    public Mono<Map<String, Object>> forecast(String companyId, Map<String, Object> body) {
        return mlWebClient.post()
                .uri("/ml/companies/{companyId}/forecast", companyId)
                .contentType(MediaType.APPLICATION_JSON)
                .header(RequestIdFilter.REQUEST_ID_HEADER, MDC.get(RequestIdFilter.REQUEST_ID_MDC_KEY))
                .bodyValue(body)
                .retrieve()
                .bodyToMono(MAP_TYPE)
                .onErrorMap(WebClientResponseException.class,
                        exception -> new WebCustomClientException(exception.getStatusCode(),
                                exception.getResponseBodyAsString(), FORECAST_UNAVAILABLE_MESSAGE))
                .onErrorMap(WebClientRequestException.class,
                        exception -> new ServiceUnavailableException(FORECAST_UNAVAILABLE_MESSAGE));
    }

    public Mono<Map<String, Object>> planFact(String companyId, LocalDate asOf, int lookbackDays) {
        return mlWebClient.get()
                .uri(uriBuilder -> uriBuilder.path("/ml/companies/{companyId}/plan-fact")
                        .queryParam("as_of", asOf.toString())
                        .queryParam("lookback_days", lookbackDays)
                        .build(companyId))
                .header(RequestIdFilter.REQUEST_ID_HEADER, MDC.get(RequestIdFilter.REQUEST_ID_MDC_KEY))
                .retrieve()
                .bodyToMono(MAP_TYPE)
                .onErrorMap(WebClientResponseException.class,
                        exception -> new WebCustomClientException(exception.getStatusCode(),
                                exception.getResponseBodyAsString(), PLAN_FACT_UNAVAILABLE_MESSAGE))
                .onErrorMap(WebClientRequestException.class,
                        exception -> new ServiceUnavailableException(PLAN_FACT_UNAVAILABLE_MESSAGE));
    }
}
