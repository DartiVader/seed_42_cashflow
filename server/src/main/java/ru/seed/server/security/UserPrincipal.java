package ru.seed.server.security;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import ru.seed.server.model.User;

import java.util.Collection;
import java.util.List;

@Getter
@RequiredArgsConstructor
public class UserPrincipal implements UserDetails {

    public static final String ROLE_ADMIN = "ADMIN";
    public static final String ROLE_ENTREPRENEUR = "ENTREPRENEUR";

    private final User user;

    public String getRole() {
        if (user.isAdmin()) {
            return ROLE_ADMIN;
        }
        return ROLE_ENTREPRENEUR;
    }

    @Override
    public Collection<? extends GrantedAuthority> getAuthorities() {
        return List.of(new SimpleGrantedAuthority("ROLE_" + getRole()));
    }

    @Override
    public String getPassword() {
        return user.getPasswordHash();
    }

    @Override
    public String getUsername() {
        return user.getEmail();
    }
}
