package ru.seed.server.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import ru.seed.server.dto.OperationDTO;
import ru.seed.server.dto.OperationRequest;
import ru.seed.server.dto.PageDTO;
import ru.seed.server.exception.AlreadyExistsException;
import ru.seed.server.exception.InvalidFieldException;
import ru.seed.server.exception.OperationNotFoundException;
import ru.seed.server.exception.Response;
import ru.seed.server.model.Direction;
import ru.seed.server.repository.CompanyRepository;
import ru.seed.server.repository.DirectionRepository;
import ru.seed.server.repository.OperationRepository;
import ru.seed.server.utils.CsvUtils;
import ru.seed.server.utils.PageUtils;
import ru.seed.server.utils.ResponseUtils;

import java.util.List;
import java.util.Optional;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class OperationService {

    private final OperationRepository operationRepository;
    private final CompanyRepository companyRepository;
    private final DirectionRepository directionRepository;
    private final CounterpartyService counterpartyService;

    @Transactional(readOnly = true)
    public Response<PageDTO<OperationDTO>> getOperations(Long userId, String companyId, int page, int size) {
        String companyFilter = companyId == null ? null : CsvUtils.optional(companyId);
        int pageNumber = PageUtils.normalizePage(page);
        int pageSize = PageUtils.normalizeSize(size);
        List<OperationDTO> items = operationRepository.findPage(
                userId, companyFilter, pageSize, PageUtils.offset(pageNumber, pageSize));
        long total = operationRepository.count(userId, companyFilter);
        return ResponseUtils.responseSuccess("getOperations", PageUtils.of(items, pageNumber, pageSize, total));
    }

    @Transactional
    public Response<OperationDTO> createOperation(Long userId, OperationRequest request) {
        normalize(request);
        Short directionId = checkAndFindDirectionId(userId, request, null);
        Long counterpartyId = counterpartyService.findOrCreate(request.getCounterpartyInn(), request.getCounterpartyName());
        Long id = operationRepository.insert(request, counterpartyId, directionId);
        return ResponseUtils.responseSuccess("createOperation", toDto(id, request));
    }

    @Transactional
    public Response<OperationDTO> updateOperation(Long userId, Long id, OperationRequest request) {
        if (!operationRepository.existsForUser(id, userId)) {
            throw new OperationNotFoundException();
        }
        normalize(request);
        Short directionId = checkAndFindDirectionId(userId, request, id);
        Long counterpartyId = counterpartyService.findOrCreate(request.getCounterpartyInn(), request.getCounterpartyName());
        operationRepository.update(id, request, counterpartyId, directionId);
        return ResponseUtils.responseSuccess("updateOperation", toDto(id, request));
    }

    @Transactional
    public Response<Void> deleteOperation(Long userId, Long id) {
        if (!operationRepository.existsForUser(id, userId)) {
            throw new OperationNotFoundException();
        }
        operationRepository.delete(id);
        return ResponseUtils.responseSuccess("deleteOperation", null);
    }

    private void normalize(OperationRequest request) {
        request.setCompanyId(request.getCompanyId().trim());
        request.setOperationId(request.getOperationId().trim());
        request.setDirection(request.getDirection().trim());
        request.setCounterpartyName(request.getCounterpartyName().trim());
        if (request.getCounterpartyInn() != null) {
            request.setCounterpartyInn(CsvUtils.optional(request.getCounterpartyInn()));
        }
        if (request.getPaymentPurpose() != null) {
            request.setPaymentPurpose(CsvUtils.optional(request.getPaymentPurpose()));
        }
    }

    private Short checkAndFindDirectionId(Long userId, OperationRequest request, Long currentId) {
        Long ownerId = companyRepository.findOwnerIds(Set.of(request.getCompanyId())).get(request.getCompanyId());
        if (!userId.equals(ownerId)) {
            throw new InvalidFieldException("companyId", "Компании " + request.getCompanyId() + " нет среди ваших");
        }
        if (!request.getOperationId().startsWith(request.getCompanyId() + "-")) {
            throw new InvalidFieldException("operationId",
                    "Номер операции должен начинаться с «" + request.getCompanyId() + "-»");
        }
        Optional<Long> sameNumberId = operationRepository.findIdBySourceOperationId(request.getOperationId());
        if (sameNumberId.isPresent() && !sameNumberId.get().equals(currentId)) {
            throw new AlreadyExistsException("operationId", "Операция с таким номером уже есть");
        }
        Direction direction = directionRepository.findByName(request.getDirection())
                .orElseThrow(() -> new InvalidFieldException("direction",
                        "Направление должно быть «Поступление» или «Списание»"));
        return direction.getId();
    }

    private OperationDTO toDto(Long id, OperationRequest request) {
        return new OperationDTO(id, request.getCompanyId(), request.getOperationId(), request.getDate(),
                request.getAmount(), request.getDirection(), request.getCounterpartyInn(),
                request.getCounterpartyName(), request.getPaymentPurpose());
    }
}
