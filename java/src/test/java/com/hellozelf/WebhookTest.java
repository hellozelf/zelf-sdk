package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.hellozelf.webhooks.EventType;
import com.hellozelf.webhooks.Webhook;
import com.hellozelf.webhooks.WebhookEvent;
import com.hellozelf.webhooks.WebhookHandler;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class WebhookTest {

    private static final String SECRET = "whsec_abcdef0123456789";
    private static final List<String> SECRETS = List.of(SECRET);
    private static final long NOW = 1718000000L;

    private static byte[] body(String type, String data) {
        return ("{\"id\":\"whd_8f2c1d4e9a\",\"type\":\"" + type
                + "\",\"subscription_id\":\"whs_5Kq9Wd2pBxLm\",\"delivered_at\":1718000000,"
                + "\"livemode\":true,\"resource\":\"content\",\"delivery_mode\":\"inline\","
                + "\"data\":" + data + "}").getBytes(StandardCharsets.UTF_8);
    }

    private static byte[] body() {
        return body("content.snapshot", "{\"item_count\":0}");
    }

    /** Mirrors the signing scheme the API documents. */
    private static String sign(byte[] payload, String secret, long timestamp) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] prefix = (timestamp + ".").getBytes(StandardCharsets.UTF_8);
            byte[] signed = new byte[prefix.length + payload.length];
            System.arraycopy(prefix, 0, signed, 0, prefix.length);
            System.arraycopy(payload, 0, signed, prefix.length, payload.length);
            StringBuilder hex = new StringBuilder();
            for (byte value : mac.doFinal(signed)) {
                hex.append(String.format("%02x", value));
            }
            return "t=" + timestamp + ",v1=" + hex;
        } catch (java.security.GeneralSecurityException error) {
            throw new IllegalStateException(error);
        }
    }

    @Test
    void parseReturnsATypedEvent() {
        byte[] payload = body("content.snapshot", "{\"item_count\":1,\"items\":[{\"id\":\"con_1\"}]}");

        WebhookEvent event = Webhook.parse(
                payload, sign(payload, SECRET, NOW), SECRETS, Webhook.Options.at(NOW));

        assertEquals(EventType.CONTENT_SNAPSHOT, event.kind());
        assertEquals("whd_8f2c1d4e9a", event.id());
        assertEquals("whs_5Kq9Wd2pBxLm", event.subscriptionId());
        assertTrue(event.livemode());
        assertEquals(1, event.items().size());
        assertTrue(event.files().isEmpty());
        assertEquals("whd_8f2c1d4e9a", event.raw().path("id").asText());
    }

    @Test
    void anUnrecognisedWireTypeLeavesTheKindNull() {
        byte[] payload = body("content.from_the_future", "{\"item_count\":0}");

        WebhookEvent event = Webhook.parse(
                payload, sign(payload, SECRET, NOW), SECRETS, Webhook.Options.at(NOW));

        assertEquals("content.from_the_future", event.type());
        assertNull(event.kind());
    }

    @Test
    void theEventTypeEnumCoversEveryDeclaredEvent() {
        for (String wire : List.of("content.snapshot", "creator.snapshot",
                "creator_vetting.completed", "ai_analysis.completed")) {
            EventType kind = EventType.fromWire(wire);
            assertNotNull(kind);
            assertEquals(wire, kind.wire());
        }
        assertNull(EventType.fromWire("content.exploded"));
        assertEquals(4, EventType.values().length);
    }

    @Test
    void aForgedSignatureIsRejected() {
        byte[] payload = body();

        assertThrows(Webhook.VerificationException.class, () -> Webhook.parse(
                payload, sign(payload, "whsec_wrong", NOW), SECRETS, Webhook.Options.at(NOW)));
    }

    @Test
    void aTamperedBodyIsRejected() {
        byte[] payload = body();
        String signature = sign(payload, SECRET, NOW);
        byte[] tampered = (new String(payload, StandardCharsets.UTF_8) + " ")
                .getBytes(StandardCharsets.UTF_8);

        assertThrows(Webhook.VerificationException.class,
                () -> Webhook.parse(tampered, signature, SECRETS, Webhook.Options.at(NOW)));
    }

    @Test
    void anOldOrFutureDeliveryIsRejectedAsAReplay() {
        byte[] payload = body();
        String signature = sign(payload, SECRET, NOW);

        assertThrows(Webhook.VerificationException.class, () -> Webhook.parse(
                payload, signature, SECRETS, Webhook.Options.at(NOW + 4000)));
        assertThrows(Webhook.VerificationException.class, () -> Webhook.parse(
                payload, signature, SECRETS, Webhook.Options.at(NOW - 4000)));
    }

    @Test
    void eitherSecretVerifiesDuringARotation() {
        byte[] payload = body();

        WebhookEvent event = Webhook.parse(payload, sign(payload, "whsec_new", NOW),
                List.of("whsec_old", "whsec_new"), Webhook.Options.at(NOW));

        assertEquals("whd_8f2c1d4e9a", event.id());
    }

    @ParameterizedTest
    @ValueSource(strings = {"garbage", "t=abc,v1=ff", "v1=ff", "t=1718000000"})
    void aMalformedSignatureHeaderIsRejected(String signature) {
        assertThrows(Webhook.VerificationException.class,
                () -> Webhook.parse(body(), signature, SECRETS, Webhook.Options.at(NOW)));
    }

    @Test
    void aMissingSignatureHeaderIsRejected() {
        assertThrows(Webhook.VerificationException.class,
                () -> Webhook.parse(body(), null, SECRETS, Webhook.Options.at(NOW)));
    }

    @Test
    void noSecretIsAConfigurationError() {
        byte[] payload = body();

        assertThrows(IllegalArgumentException.class, () -> Webhook.parse(
                payload, sign(payload, SECRET, NOW), List.of(), Webhook.Options.at(NOW)));
    }

    @Test
    void theHandlerRoutesToTheListenerForTheType() {
        List<String> seen = new ArrayList<>();
        WebhookHandler handler = new WebhookHandler(SECRETS, Webhook.Options.at(NOW))
                .on(event -> seen.add("content:" + event.id()), EventType.CONTENT_SNAPSHOT)
                .on(event -> seen.add("creator"), EventType.CREATOR_SNAPSHOT);

        byte[] payload = body();
        handler.handle(payload, sign(payload, SECRET, NOW));

        assertEquals(List.of("content:whd_8f2c1d4e9a"), seen);
    }

    @Test
    void anUnmatchedEventFallsBackOrIsANoOp() {
        List<String> seen = new ArrayList<>();
        byte[] payload = body("ai_analysis.completed", "{\"item_count\":0}");
        String signature = sign(payload, SECRET, NOW);

        new WebhookHandler(SECRETS, Webhook.Options.at(NOW))
                .onAny(event -> seen.add(event.type()))
                .handle(payload, signature);
        new WebhookHandler(SECRETS, Webhook.Options.at(NOW)).handle(payload, signature);

        assertEquals(List.of("ai_analysis.completed"), seen);
    }

    @Test
    void noListenerRunsWhenTheSignatureIsBad() {
        List<String> seen = new ArrayList<>();
        WebhookHandler handler = new WebhookHandler(SECRETS, Webhook.Options.at(NOW))
                .onAny(event -> seen.add(event.type()));
        byte[] payload = body();

        assertThrows(Webhook.VerificationException.class,
                () -> handler.handle(payload, sign(payload, "whsec_wrong", NOW)));
        assertTrue(seen.isEmpty());
    }

    @Test
    void registeringNoEventTypeIsRejected() {
        WebhookHandler handler = new WebhookHandler(SECRETS, Webhook.Options.defaults());

        assertThrows(IllegalArgumentException.class, () -> handler.on(event -> { }));
    }
}
