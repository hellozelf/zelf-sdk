package com.hellozelf;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.deser.std.NumberDeserializers;
import com.fasterxml.jackson.databind.deser.std.StdDeserializer;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.module.SimpleModule;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.io.IOException;
import java.io.InputStream;
import java.math.RoundingMode;

/**
 * Decodes a downloaded report: the JSON behind a run's {@code result.download_url}, as
 * {@code AiAnalysisReport}, {@code AdvancedAiAnalysisReport} or {@code CreatorVettingReport}.
 *
 * <p>Reports are written by the AI pipeline, so a field can be null, missing, or a decimal where
 * a whole number is expected. None of those fail the decode: a missing or null field reads as
 * null, and a decimal reads as the nearest whole number.
 */
public final class ZelfReports {

    private static final ObjectMapper MAPPER = JsonMapper.builder()
            .addModule(new JavaTimeModule())
            .addModule(new SimpleModule().addDeserializer(Long.class, new LenientLong()))
            .build();

    private ZelfReports() {}

    /** Decodes a report from its JSON text. */
    public static <T> T decode(String json, Class<T> type) throws IOException {
        return MAPPER.readValue(json, type);
    }

    /** Decodes a report from a stream, such as the download response body. */
    public static <T> T decode(InputStream json, Class<T> type) throws IOException {
        return MAPPER.readValue(json, type);
    }

    /** Reads a whole number, or a decimal rounded to the nearest whole number. */
    static final class LenientLong extends StdDeserializer<Long> {

        private static final NumberDeserializers.LongDeserializer STANDARD =
                new NumberDeserializers.LongDeserializer(Long.class, null);

        LenientLong() {
            super(Long.class);
        }

        @Override
        public Long deserialize(JsonParser parser, DeserializationContext context) throws IOException {
            if (parser.currentToken() == JsonToken.VALUE_NUMBER_FLOAT) {
                return parser.getDecimalValue().setScale(0, RoundingMode.HALF_UP).longValueExact();
            }
            return STANDARD.deserialize(parser, context);
        }
    }
}
