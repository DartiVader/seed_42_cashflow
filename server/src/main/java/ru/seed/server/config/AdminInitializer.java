package ru.seed.server.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import ru.seed.server.service.UserService;

@Slf4j
@Component
@RequiredArgsConstructor
public class AdminInitializer implements ApplicationRunner {

    private final AdminProperties adminProperties;
    private final UserService userService;

    @Override
    public void run(ApplicationArguments args) {
        if (!StringUtils.hasText(adminProperties.getEmail()) || !StringUtils.hasText(adminProperties.getPassword())) {
            log.warn("ADMIN_EMAIL or ADMIN_PASSWORD is not set, admin user is not created");
            return;
        }
        userService.createAdminIfAbsent(adminProperties.getEmail(), adminProperties.getPassword());
    }
}
