package ru.seed.server.dto;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public abstract class CsvRow {
    private int lineNumber;
}
