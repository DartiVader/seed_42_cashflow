package ru.seed.server.utils;

import ru.seed.server.dto.PageDTO;

import java.util.List;

public final class PageUtils {

    public static final int MAX_SIZE = 100;

    private PageUtils() {
    }

    public static int normalizePage(int page) {
        return Math.max(page, 0);
    }

    public static int normalizeSize(int size) {
        return Math.min(Math.max(size, 1), MAX_SIZE);
    }

    public static long offset(int page, int size) {
        return (long) page * size;
    }

    public static <T> PageDTO<T> of(List<T> items, int page, int size, long totalElements) {
        int totalPages = (int) ((totalElements + size - 1) / size);
        return new PageDTO<>(items, page, size, totalElements, totalPages);
    }
}
