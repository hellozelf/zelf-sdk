package com.hellozelf;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;

/** The response wrapper every Zelf endpoint returns. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record Envelope<T>(
        @JsonProperty("log_id") String logId,
        @JsonProperty("timestamp") String timestamp,
        @JsonProperty("results") List<T> results,
        @JsonProperty("item_count") int itemCount,
        @JsonProperty("page") int page,
        @JsonProperty("next") Integer next,
        @JsonProperty("previous") Integer previous,
        @JsonProperty("applied_filters") JsonNode appliedFilters) {

    public List<T> results() {
        return results == null ? List.of() : results;
    }
}
