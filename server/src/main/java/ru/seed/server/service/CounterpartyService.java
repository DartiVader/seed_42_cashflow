package ru.seed.server.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import ru.seed.server.repository.CounterpartyRepository;

import java.util.Set;

@Service
@RequiredArgsConstructor
public class CounterpartyService {

    private final CounterpartyRepository counterpartyRepository;

    public Long findOrCreate(String inn, String name) {
        if (inn != null) {
            Long id = counterpartyRepository.findIdsByInn(Set.of(inn)).get(inn);
            if (id != null) {
                return id;
            }
            return counterpartyRepository.insert(inn, name);
        }
        Long id = counterpartyRepository.findIdsByNameWithoutInn(Set.of(name)).get(name);
        if (id != null) {
            return id;
        }
        return counterpartyRepository.insert(null, name);
    }
}
