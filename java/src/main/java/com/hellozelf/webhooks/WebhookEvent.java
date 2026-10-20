package com.hellozelf.webhooks;

import com.fasterxml.jackson.databind.JsonNode;
import java.net.http.HttpClient;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

/** A delivery whose signature has already been checked. */
public final class WebhookEvent {

    private final JsonNode raw;

    WebhookEvent(JsonNode raw) {
        this.raw = raw;
    }

    /** The payload exactly as it arrived, including fields this SDK predates. */
    public JsonNode raw() {
        return raw;
    }

    public String id() {
        return raw.path("id").asText("");
    }

    /** The wire value, which may be newer than this SDK's {@link EventType}. */
    public String type() {
        return raw.path("type").asText("");
    }

    /** The declared event type, or null for one the SDK predates. */
    public EventType kind() {
        return EventType.fromWire(type());
    }

    public String subscriptionId() {
        return raw.path("subscription_id").asText("");
    }

    public Instant deliveredAt() {
        return Instant.ofEpochSecond(raw.path("delivered_at").asLong(0));
    }

    public boolean livemode() {
        return raw.path("livemode").asBoolean(false);
    }

    public String deliveryMode() {
        return raw.path("delivery_mode").asText("");
    }

    public int itemCount() {
        return raw.path("data").path("item_count").asInt(0);
    }

    /** Downloadable snapshot files. Populated in manifest mode only. */
    public List<JsonNode> files() {
        List<JsonNode> out = new ArrayList<>();
        raw.path("data").path("files").forEach(out::add);
        return out;
    }

    /** Rows carried in the body. Populated in inline mode only. */
    public List<JsonNode> items() {
        List<JsonNode> out = new ArrayList<>();
        raw.path("data").path("items").forEach(out::add);
        return out;
    }

    public JsonNode statistics() {
        return raw.path("data").path("statistics");
    }

    @Override
    public String toString() {
        return "WebhookEvent(" + type() + ", id=" + id() + ", items=" + itemCount() + ")";
    }

    /**
     * Download the manifest files and hand each decoded row to {@code visit}.
     *
     * <p>Each download URL is signed and expires, so fetch soon after
     * delivery. With {@code verifyChecksum} the published SHA-256 is
     * recomputed over the body, and a mismatch or a missing digest throws
     * before any row.
     */
    public void rows(HttpClient http, boolean verifyChecksum, Consumer<JsonNode> visit) {
        for (JsonNode handle : files()) {
            Webhook.download(
                    http,
                    handle.path("download_url").asText(),
                    handle.path("sha256").asText(""),
                    verifyChecksum,
                    visit);
        }
    }
}
