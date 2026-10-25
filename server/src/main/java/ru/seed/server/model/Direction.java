package ru.seed.server.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Immutable;

@Entity
@Immutable
@Table(name = "direction")
@Getter
@NoArgsConstructor
public class Direction {
    @Id
    private Short id;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private Short sign;
}
