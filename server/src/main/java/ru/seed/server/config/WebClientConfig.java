package ru.seed.server.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
@EnableConfigurationProperties({MlProperties.class, LlmProperties.class})
public class WebClientConfig {

    @Bean
    public WebClient mlWebClient(MlProperties properties) {
        return WebClient.builder().baseUrl(properties.getUrl()).build();
    }

    @Bean
    public WebClient llmWebClient(LlmProperties properties) {
        return WebClient.builder().baseUrl(properties.getUrl()).build();
    }
}
