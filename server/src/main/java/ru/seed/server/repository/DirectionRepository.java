package ru.seed.server.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import ru.seed.server.model.Direction;

import java.util.Optional;

@Repository
public interface DirectionRepository extends JpaRepository<Direction, Short> {

    Optional<Direction> findByName(String name);
}
