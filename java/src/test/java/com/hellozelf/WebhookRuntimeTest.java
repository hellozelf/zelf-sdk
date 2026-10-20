package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.hellozelf.webhooks.EventType;
import com.hellozelf.webhooks.Webhook;
import com.hellozelf.webhooks.WebhookEvent;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;

/** Signature verification, event accessors and manifest downloads. */
class WebhookRuntimeTest {

    private static final String SECRET = "whsec_abcdef0123456789";

    private static String sign(byte[] payload, long timestamp) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update((timestamp + ".").getBytes(StandardCharsets.UTF_8));
        mac.update(payload);
        return "t=" + timestamp + ",v1=" + HexFormat.of().formatHex(mac.doFinal());
    }

    private static byte[] push(String deliveryMode, String data) {
        return ("{\"id\":\"whd_1\",\"type\":\"content.snapshot\",\"subscription_id\":\"whs_1\","
                + "\"delivered_at\":1718000000,\"livemode\":true,\"resource\":\"content\","
                + "\"delivery_mode\":\"" + deliveryMode + "\",\"data\":" + data + "}")
                .getBytes(StandardCharsets.UTF_8);
    }

    @Test
    void anEventExposesEveryAccessor() throws Exception {
        byte[] payload = push("inline",
                "{\"item_count\":1,\"items\":[{\"id\":\"con_1\"}],\"statistics\":{\"post_count\":1}}");
        WebhookEvent event = Webhook.parse(payload, sign(payload, System.currentTimeMillis() / 1000),
                List.of(SECRET), Webhook.Options.defaults());

        assertEquals("whd_1", event.id());
        assertEquals(EventType.CONTENT_SNAPSHOT.wire(), event.type());
        assertEquals(EventType.CONTENT_SNAPSHOT, event.kind());
        assertEquals("content.snapshot", EventType.CONTENT_SNAPSHOT.wire());
        assertEquals("inline", event.deliveryMode());
        assertEquals(1, event.itemCount());
        assertNotNull(event.deliveredAt());
        assertNotNull(event.statistics());
        assertTrue(event.toString().contains("WebhookEvent("));
        assertEquals(1, event.items().size());
    }

    @Test
    void aBodyThatIsNotAJsonObjectIsRefused() throws Exception {
        byte[] payload = "[1,2,3]".getBytes(StandardCharsets.UTF_8);
        String signature = sign(payload, System.currentTimeMillis() / 1000);
        assertThrows(Webhook.VerificationException.class,
                () -> Webhook.verify(payload, signature, List.of(SECRET), Webhook.Options.defaults()));
    }

    @Test
    void aBodyThatIsNotJsonIsRefused() throws Exception {
        byte[] payload = "not json".getBytes(StandardCharsets.UTF_8);
        String signature = sign(payload, System.currentTimeMillis() / 1000);
        assertThrows(Webhook.VerificationException.class,
                () -> Webhook.verify(payload, signature, List.of(SECRET), Webhook.Options.defaults()));
    }

    @Test
    void rowsDownloadsAndVerifiesTheManifest() throws Exception {
        byte[] file = "{\"id\":\"con_1\"}\n\n{\"id\":\"con_2\"}\n".getBytes(StandardCharsets.UTF_8);
        String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(file));

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/file", exchange -> {
            exchange.sendResponseHeaders(200, file.length);
            exchange.getResponseBody().write(file);
            exchange.close();
        });
        server.createContext("/broken", exchange -> {
            exchange.sendResponseHeaders(500, -1);
            exchange.close();
        });
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort();

        try {
            byte[] payload = push("manifest", "{\"item_count\":2,\"files\":[{\"download_url\":\""
                    + base + "/file\",\"sha256\":\"" + digest + "\"}]}");
            WebhookEvent event = Webhook.parse(payload,
                    sign(payload, System.currentTimeMillis() / 1000), List.of(SECRET), Webhook.Options.defaults());

            List<String> seen = new ArrayList<>();
            event.rows(java.net.http.HttpClient.newHttpClient(), true,
                    row -> seen.add(row.path("id").asText()));
            assertEquals(List.of("con_1", "con_2"), seen);

            byte[] wrong = push("manifest", "{\"item_count\":1,\"files\":[{\"download_url\":\""
                    + base + "/file\",\"sha256\":\"" + "0".repeat(64) + "\"}]}");
            WebhookEvent tampered = Webhook.parse(wrong,
                    sign(wrong, System.currentTimeMillis() / 1000), List.of(SECRET), Webhook.Options.defaults());
            assertThrows(Webhook.VerificationException.class,
                    () -> tampered.rows(java.net.http.HttpClient.newHttpClient(), true, row -> { }));

            byte[] broken = push("manifest", "{\"item_count\":1,\"files\":[{\"download_url\":\""
                    + base + "/broken\",\"sha256\":\"\"}]}");
            WebhookEvent failing = Webhook.parse(broken,
                    sign(broken, System.currentTimeMillis() / 1000), List.of(SECRET), Webhook.Options.defaults());
            assertThrows(Webhook.VerificationException.class,
                    () -> failing.rows(java.net.http.HttpClient.newHttpClient(), true, row -> { }));

            byte[] unsigned = push("manifest", "{\"item_count\":2,\"files\":[{\"download_url\":\""
                    + base + "/file\",\"sha256\":\"\"}]}");
            WebhookEvent unchecked_ = Webhook.parse(unsigned,
                    sign(unsigned, System.currentTimeMillis() / 1000), List.of(SECRET), Webhook.Options.defaults());
            assertThrows(Webhook.VerificationException.class,
                    () -> unchecked_.rows(java.net.http.HttpClient.newHttpClient(), true, row -> { }));

            List<String> waived = new ArrayList<>();
            unchecked_.rows(java.net.http.HttpClient.newHttpClient(), false,
                    row -> waived.add(row.path("id").asText()));
            assertEquals(List.of("con_1", "con_2"), waived);

            byte[] missing = push("manifest", "{\"item_count\":1,\"files\":[{\"download_url\":\""
                    + base + "/gone-away\",\"sha256\":\"\"}]}");
            WebhookEvent absent = Webhook.parse(missing,
                    sign(missing, System.currentTimeMillis() / 1000), List.of(SECRET), Webhook.Options.defaults());
            assertThrows(Webhook.VerificationException.class,
                    () -> absent.rows(java.net.http.HttpClient.newHttpClient(), true, row -> { }));
        } finally {
            server.stop(0);
        }
    }

    @Test
    void anUnreachableDownloadIsReported() throws Exception {
        byte[] payload = push("manifest", "{\"item_count\":1,\"files\":[{\"download_url\":"
                + "\"http://127.0.0.1:1/gone\",\"sha256\":\"\"}]}");
        WebhookEvent event = Webhook.parse(payload,
                sign(payload, System.currentTimeMillis() / 1000), List.of(SECRET),
                Webhook.Options.defaults());
        assertThrows(Webhook.VerificationException.class,
                () -> event.rows(java.net.http.HttpClient.newHttpClient(), true, row -> { }));
    }

    @Test
    void anEventTypePrintsItsWireName() {
        for (EventType type : EventType.values()) {
            assertEquals(type.wire(), type.toString());
        }
    }
}
