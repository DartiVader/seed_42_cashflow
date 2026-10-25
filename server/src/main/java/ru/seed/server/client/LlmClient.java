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

import java.util.Map;

@Component
public class LlmClient {

    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE = new ParameterizedTypeReference<>() {
    };

    private static final String UNAVAILABLE_MESSAGE = "Объяснение сейчас недоступно";

    private final WebClient llmWebClient;

    public LlmClient(@Qualifier("llmWebClient") WebClient llmWebClient) {
        this.llmWebClient = llmWebClient;
    }

    public Mono<Map<String, Object>> explain(Map<String, Object> body) {
        return llmWebClient.post()
                .uri("/explain")
                .contentType(MediaType.APPLICATION_JSON)
                .header(RequestIdFilter.REQUEST_ID_HEADER, MDC.get(RequestIdFilter.REQUEST_ID_MDC_KEY))
                .bodyValue(body)
                .retrieve()
                .bodyToMono(MAP_TYPE)
                .onErrorMap(WebClientResponseException.class,
                        exception -> new WebCustomClientException(exception.getStatusCode(),
                                exception.getResponseBodyAsString(), UNAVAILABLE_MESSAGE))
                .onErrorMap(WebClientRequestException.class,
                        exception -> new ServiceUnavailableException(UNAVAILABLE_MESSAGE));
    }
}
