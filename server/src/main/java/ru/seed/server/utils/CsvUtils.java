package ru.seed.server.utils;

import ru.seed.server.exception.CsvFormatException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

public final class CsvUtils {

    private static final String SEPARATOR = ";";
    private static final char BOM = '﻿';
    private static final DateTimeFormatter RUSSIAN_DATE =
            DateTimeFormatter.ofPattern("dd.MM.uuuu").withResolverStyle(ResolverStyle.STRICT);
    private static final BigDecimal MAX_AMOUNT = new BigDecimal("10000000000000");
    private static final Pattern DIGITS = Pattern.compile("\\d{1,12}");

    private CsvUtils() {
    }

    public static String[] split(String line) {
        return line.split(SEPARATOR, -1);
    }

    public static List<String> splitHeader(String line) {
        String withoutBom = line;
        if (!line.isEmpty() && line.charAt(0) == BOM) {
            withoutBom = line.substring(1);
        }
        List<String> columns = new ArrayList<>();
        for (String column : split(withoutBom)) {
            columns.add(column.trim());
        }
        return columns;
    }

    public static String join(String[] values, int from, int to) {
        List<String> parts = new ArrayList<>();
        for (int index = from; index < to; index++) {
            parts.add(values[index]);
        }
        return String.join(SEPARATOR, parts);
    }

    public static String required(String value, String title, int maxLength) {
        String trimmed = value.trim();
        if (trimmed.isEmpty()) {
            throw new CsvFormatException("Не заполнено поле «" + title + "»");
        }
        if (trimmed.length() > maxLength) {
            throw new CsvFormatException("Поле «" + title + "» длиннее " + maxLength + " символов");
        }
        return trimmed;
    }

    public static String optional(String value) {
        String trimmed = value.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        return trimmed;
    }

    public static LocalDate parseDate(String value) {
        String trimmed = value.trim();
        DateTimeFormatter format = trimmed.contains(".") ? RUSSIAN_DATE : DateTimeFormatter.ISO_LOCAL_DATE;
        try {
            return LocalDate.parse(trimmed, format);
        } catch (DateTimeParseException exception) {
            throw new CsvFormatException("Дата «" + trimmed + "» не распознана, нужен формат ГГГГ-ММ-ДД");
        }
    }

    public static BigDecimal parseAmount(String value) {
        String trimmed = value.trim();
        BigDecimal amount;
        try {
            amount = new BigDecimal(trimmed);
        } catch (NumberFormatException exception) {
            throw new CsvFormatException("Сумма «" + trimmed + "» не распознана, нужен формат 12345.67");
        }
        if (amount.signum() <= 0) {
            throw new CsvFormatException("Сумма должна быть больше нуля");
        }
        if (amount.scale() > 2) {
            throw new CsvFormatException("В сумме больше двух знаков после точки");
        }
        if (amount.compareTo(MAX_AMOUNT) >= 0) {
            throw new CsvFormatException("Сумма слишком большая");
        }
        return amount;
    }

    public static String normalizeInn(String value) {
        String trimmed = value.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        if (!DIGITS.matcher(trimmed).matches()) {
            throw new CsvFormatException("ИНН должен состоять из 10 или 12 цифр");
        }
        if (trimmed.length() < 10) {
            return "0".repeat(10 - trimmed.length()) + trimmed;
        }
        if (trimmed.length() == 11) {
            return "0" + trimmed;
        }
        return trimmed;
    }
}
