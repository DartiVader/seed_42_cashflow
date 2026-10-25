package ru.seed.server.mapper;

import org.springframework.stereotype.Component;
import ru.seed.server.dto.UserDTO;
import ru.seed.server.model.User;

@Component
public class UserMapper {

    public UserDTO toDto(User user) {
        return new UserDTO(user.getId(), user.getEmail(), user.isAdmin());
    }
}
