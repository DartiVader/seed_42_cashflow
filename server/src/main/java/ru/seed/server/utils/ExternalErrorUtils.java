package ru.seed.server.utils;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class ExternalErrorUtils {

    private static final Pattern MESSAGE_PATTERN =
            Pattern.compile("\"(?:message|detail)\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");

    private ExternalErrorUtils() {
    }

    public static String extractMessage(String responseBody, String defaultMessage) {
        if (responseBody == null) {
            return defaultMessage;
        }
        Matcher matcher = MESSAGE_PATTERN.matcher(responseBody);
        if (matcher.find()) {
            return matcher.group(1).replace("\\\"", "\"");
        }
        return defaultMessage;
    }
}
