package com.hellozelf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Response examples lifted from the spec, so fixtures match the schemas. */
public final class Fixtures {

    public static final String API_KEY = "sk_test_not_a_real_key";

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final JsonNode ROOT = load();

    private Fixtures() {
    }

    private static JsonNode load() {
        try {
            return MAPPER.readTree(Files.readString(Path.of("..", "fixtures.json")));
        } catch (IOException error) {
            throw new IllegalStateException("fixtures.json is missing", error);
        }
    }

    public static String contentRow(String id) {
        ObjectNode row = ROOT.path("envelopes").path("content_list").path("results").get(0).deepCopy();
        row.put("id", id);
        return row.toString();
    }

    public static String envelope(String results, int page, String next) {
        return "{\"log_id\":\"log_1\",\"timestamp\":\"2026-01-01T00:00:00Z\","
                + "\"applied_filters\":{},\"results\":" + results
                + ",\"item_count\":1,\"page\":" + page
                + ",\"next\":" + next + ",\"previous\":null}";
    }

    public static String envelope(String results) {
        return envelope(results, 1, "null");
    }
}
