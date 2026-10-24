package ru.seed.server.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import ru.seed.server.model.LegalForm;

import java.util.Optional;

@Repository
public interface LegalFormRepository extends JpaRepository<LegalForm, Short> {

    Optional<LegalForm> findByCode(String code);
}
