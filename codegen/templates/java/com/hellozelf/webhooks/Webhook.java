package com.hellozelf.webhooks;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.function.Consumer;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Verifies and routes the deliveries Zelf posts to a receiver. */
public final class Webhook {

    public static final String SIGNATURE_HEADER = "Webhook-Signature";
    public static final String TIMESTAMP_HEADER = "Webhook-Timestamp";
    public static final String ID_HEADER = "Webhook-Id";

    /** How far a timestamp may sit from now before it reads as a replay. */
    public static final long DEFAULT_TOLERANCE_SECONDS = 300;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Webhook() {
    }

    /** Tunes verification. */
    public record Options(long toleranceSeconds, Long now) {
        public static Options defaults() {
            return new Options(DEFAULT_TOLERANCE_SECONDS, null);
        }

        /** Treat the given unix second as now. For tests. */
        public static Options at(long seconds) {
            return new Options(DEFAULT_TOLERANCE_SECONDS, seconds);
        }
    }

    /** Raised for every failed verification. Answer one with a 400. */
    public static final class VerificationException extends RuntimeException {
        public VerificationException(String message) {
            super(message);
        }
    }

    private record Signature(long timestamp, List<String> digests) {
    }

    private static Signature parseSignature(String raw) {
        Long timestamp = null;
        List<String> digests = new ArrayList<>();
        for (String part : raw.split(",")) {
            String[] pair = part.trim().split("=", 2);
            if (pair.length != 2) {
                continue;
            }
            if (pair[0].equals("t") && timestamp == null) {
                try {
                    timestamp = Long.parseLong(pair[1]);
                } catch (NumberFormatException error) {
                    throw new VerificationException("Signature timestamp is not an integer.");
                }
            } else if (pair[0].equals("v1")) {
                digests.add(pair[1]);
            }
        }
        if (timestamp == null || digests.isEmpty()) {
            throw new VerificationException("Signature header is missing a t or v1 component.");
        }
        return new Signature(timestamp, digests);
    }

    private static byte[] hmac(String secret, byte[] signed) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return mac.doFinal(signed);
        } catch (java.security.GeneralSecurityException error) {
            throw new IllegalStateException("HmacSHA256 is unavailable.", error);
        }
    }

    static byte[] fromHex(String hex) {
        if (hex.length() % 2 != 0 || !hex.matches("[0-9a-fA-F]+")) {
            return null;
        }
        byte[] out = new byte[hex.length() / 2];
        for (int index = 0; index < out.length; index++) {
            out[index] = (byte) Integer.parseInt(hex.substring(index * 2, index * 2 + 2), 16);
        }
        return out;
    }

    static String toHex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            out.append(String.format("%02x", value));
        }
        return out.toString();
    }

    /**
     * Verify a delivery and return the decoded payload.
     *
     * <p>The payload must be the exact bytes received: re-encoding the JSON
     * changes the bytes and the signature will not match.
     *
     * <p>A rotation switches at once: the API signs the next delivery with the
     * new secret only and rejects the old one immediately. A list of secrets
     * is accepted, so both can be held during a rollout.
     *
     * <p>The comparison runs through MessageDigest.isEqual, which is constant
     * time, so a wrong signature cannot be recovered from response timing.
     */
    public static JsonNode verify(
            byte[] payload, String signature, List<String> secrets, Options options) {
        if (secrets == null || secrets.isEmpty()) {
            throw new IllegalArgumentException("At least one signing secret is required.");
        }
        if (signature == null || signature.isEmpty()) {
            throw new VerificationException("Missing " + SIGNATURE_HEADER + " header.");
        }
        Options settings = options == null ? Options.defaults() : options;
        Signature parsed = parseSignature(signature);

        if (settings.toleranceSeconds() > 0) {
            long now = settings.now() != null ? settings.now() : System.currentTimeMillis() / 1000;
            long age = Math.abs(now - parsed.timestamp());
            if (age > settings.toleranceSeconds()) {
                throw new VerificationException(
                        "Webhook timestamp is " + age + "s away from now, outside the "
                                + settings.toleranceSeconds()
                                + "s tolerance. Treating it as a replay.");
            }
        }

        byte[] prefix = (parsed.timestamp() + ".").getBytes(StandardCharsets.UTF_8);
        byte[] signed = new byte[prefix.length + payload.length];
        System.arraycopy(prefix, 0, signed, 0, prefix.length);
        System.arraycopy(payload, 0, signed, prefix.length, payload.length);

        boolean matched = false;
        for (String secret : secrets) {
            byte[] want = hmac(secret, signed);
            for (String digest : parsed.digests()) {
                byte[] got = fromHex(digest);
                if (got != null && MessageDigest.isEqual(want, got)) {
                    matched = true;
                }
            }
        }
        if (!matched) {
            throw new VerificationException("No signature matched the supplied secret(s).");
        }

        try {
            JsonNode body = MAPPER.readTree(payload);
            if (body == null || !body.isObject()) {
                throw new VerificationException("Webhook body is not a JSON object.");
            }
            return body;
        } catch (java.io.IOException error) {
            throw new VerificationException("Webhook body is not valid JSON.");
        }
    }

    /** Verify a delivery and return it as a typed event. */
    public static WebhookEvent parse(
            byte[] payload, String signature, List<String> secrets, Options options) {
        return new WebhookEvent(verify(payload, signature, secrets, options));
    }

    /** Download a manifest file and hand each decoded row to {@code visit}. */
    static void download(
            HttpClient http, String url, String sha256, boolean verifyChecksum,
            Consumer<JsonNode> visit) {
        try {
            HttpResponse<byte[]> response = http.send(
                    HttpRequest.newBuilder(URI.create(url)).GET().build(),
                    HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() >= 400) {
                throw new VerificationException(
                        "Downloading the snapshot failed with HTTP " + response.statusCode() + ".");
            }
            byte[] body = response.body();
            if (verifyChecksum) {
                if (sha256 == null || sha256.isEmpty()) {
                    throw new VerificationException(
                            "The manifest published no sha256 for " + url + ", so the file"
                                    + " cannot be verified. Pass verifyChecksum false to read"
                                    + " it unchecked.");
                }
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(body);
                if (!MessageDigest.isEqual(digest, fromHex(sha256))) {
                    throw new VerificationException(
                            "Downloaded file digest " + toHex(digest)
                                    + " does not match the published " + sha256 + ".");
                }
            }
            for (String line : new String(body, StandardCharsets.UTF_8).split("\n")) {
                if (!line.isBlank()) {
                    visit.accept(MAPPER.readTree(line));
                }
            }
        } catch (java.io.IOException | java.security.NoSuchAlgorithmException error) {
            throw new VerificationException("Downloading the snapshot failed: " + error.getMessage());
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new VerificationException("The snapshot download was interrupted.");
        }
    }

    static List<String> secretsOf(String... values) {
        return Arrays.asList(values);
    }
}
