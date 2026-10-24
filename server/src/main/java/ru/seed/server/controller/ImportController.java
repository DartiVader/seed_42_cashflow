package ru.seed.server.controller;

import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import ru.seed.server.dto.ImportReportDTO;
import ru.seed.server.exception.Response;
import ru.seed.server.service.csv.CsvImportService;

@RestController
@RequestMapping("/api/imports")
@RequiredArgsConstructor
public class ImportController {

    private final CsvImportService csvImportService;

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Response<ImportReportDTO> importFile(@RequestPart("file") MultipartFile file,
                                                @AuthenticationPrincipal Jwt jwt) {
        return csvImportService.importFile(Long.valueOf(jwt.getSubject()), file);
    }
}
