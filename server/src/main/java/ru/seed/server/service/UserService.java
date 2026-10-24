package ru.seed.server.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.UserDTO;
import ru.seed.server.exception.AlreadyExistsException;
import ru.seed.server.exception.Response;
import ru.seed.server.exception.UserNotFoundException;
import ru.seed.server.mapper.UserMapper;
import ru.seed.server.model.User;
import ru.seed.server.repository.UserRepository;
import ru.seed.server.utils.EmailUtils;
import ru.seed.server.utils.ResponseUtils;

@Slf4j
@Service
@RequiredArgsConstructor
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final UserMapper userMapper;

    @Transactional(readOnly = true)
    public Response<UserDTO> getCurrentUser(Long userId) {
        User user = userRepository.findById(userId).orElseThrow(UserNotFoundException::new);
        return ResponseUtils.responseSuccess("getCurrentUser", userMapper.toDto(user));
    }

    @Transactional
    public User create(String email, String rawPassword, boolean isAdmin) {
        String normalizedEmail = EmailUtils.normalize(email);
        if (userRepository.existsByEmail(normalizedEmail)) {
            throw new AlreadyExistsException("email", "Пользователь с таким email уже зарегистрирован");
        }

        User user = new User();
        user.setEmail(normalizedEmail);
        user.setPasswordHash(passwordEncoder.encode(rawPassword));
        user.setAdmin(isAdmin);
        User saved = userRepository.save(user);

        log.info("User created, userId={}, isAdmin={}", saved.getId(), saved.isAdmin());
        return saved;
    }

    @Transactional
    public void createAdminIfAbsent(String email, String rawPassword) {
        if (userRepository.existsByEmail(EmailUtils.normalize(email))) {
            return;
        }
        create(email, rawPassword, true);
    }
}
