package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hellozelf.model.AdvancedAiAnalysisReport;
import com.hellozelf.model.AdvancedSummary;
import com.hellozelf.model.AiAnalysisReport;
import com.hellozelf.model.CreatorVettingReport;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ReportsTest {

    private static final Map<String, Class<?>> TYPES = Map.of(
            "AiAnalysisReport", AiAnalysisReport.class,
            "AdvancedAiAnalysisReport", AdvancedAiAnalysisReport.class,
            "CreatorVettingReport", CreatorVettingReport.class);

    private static JsonNode reports() throws IOException {
        return new ObjectMapper()
                .readTree(Files.readString(Path.of("..", "fixtures", "fixtures.json")))
                .path("reports");
    }

    @Test
    void everyMalformedReportCaseDecodes() throws IOException {
        JsonNode reports = reports();
        for (Map.Entry<String, Class<?>> entry : TYPES.entrySet()) {
            reports.path(entry.getKey()).fields().forEachRemaining(kase -> {
                try {
                    assertNotNull(ZelfReports.decode(kase.getValue().toString(), entry.getValue()));
                } catch (IOException error) {
                    throw new AssertionError(entry.getKey() + "." + kase.getKey(), error);
                }
            });
        }
    }

    @Test
    void decimalRoundsToNearestWhole() throws IOException {
        String document = reports().path("AdvancedAiAnalysisReport").path("decimals").toString();
        AdvancedAiAnalysisReport report = ZelfReports.decode(
                new ByteArrayInputStream(document.getBytes(StandardCharsets.UTF_8)),
                AdvancedAiAnalysisReport.class);
        assertEquals(13L, report.summary().videos());
        assertEquals(13L, report.topCreators().get(0).posts());
    }

    @Test
    void wholeNumbersNullsAndMissingFieldsRead() throws IOException {
        AdvancedSummary summary = ZelfReports.decode(
                "{\"videos\": 9007199254740993, \"creators\": null, \"total_views\": -2.5}",
                AdvancedSummary.class);
        assertEquals(9007199254740993L, summary.videos());
        assertNull(summary.creators());
        assertEquals(-3L, summary.totalViews());
        assertNull(summary.totalLikes());
    }

    @Test
    void textInAWholeNumberFieldStillFails() {
        assertThrows(IOException.class,
                () -> ZelfReports.decode("{\"videos\": [1]}", AdvancedSummary.class));
    }
}
