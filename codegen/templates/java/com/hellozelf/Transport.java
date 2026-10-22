package com.hellozelf;

import com.fasterxml.jackson.databind.JavaType;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/** Carries out the HTTP work: auth, retries, and envelope decoding. */
public final class Transport {

    /** The production Zelf API. */
    public static final String DEFAULT_BASE_URL = "https://api.hellozelf.com";

    /** Read when no key is set explicitly. */
    public static final String API_KEY_ENV = "ZELF_API_KEY";

    /** Read when no base URL is passed explicitly. */
    public static final String BASE_URL_ENV = "ZELF_BASE_URL";

    static final ObjectMapper MAPPER = JsonMapper.builder()
            .addModule(new JavaTimeModule())
            .build()
            .findAndRegisterModules();

    private static final Set<Integer> RETRY_STATUSES = Set.of(429, 500, 502, 503, 504);
    // The API documents no Idempotency-Key header, so a retried write could
    // create a second analysis, vetting, or sync job.
    private static final Set<String> RETRY_SAFE_METHODS = Set.of("GET", "HEAD", "OPTIONS");
    private static final long MAX_BACKOFF_MILLIS = 8_000L;

    private final HttpClient http;
    private final String apiKey;
    private final String baseUrl;
    private final int maxRetries;
    private final boolean retryWrites;
    private final Map<String, String> headers;
    private final Duration timeout;

    Transport(ZelfClientOptions options) {
        String key = options.apiKey() != null ? options.apiKey() : System.getenv(API_KEY_ENV);
        if (key == null || key.isEmpty()) {
            throw new IllegalArgumentException(
                    "An API key is required. Set apiKey or " + API_KEY_ENV + ".");
        }
        if (options.maxRetries() < 0) {
            throw new IllegalArgumentException("maxRetries must be zero or greater.");
        }
        this.apiKey = key;
        this.baseUrl = options.baseUrl().replaceAll("/+$", "");
        this.maxRetries = options.maxRetries();
        this.retryWrites = options.retryWrites();
        // A caller's copy of the API key is dropped whatever its casing, so it
        // cannot be appended alongside the client's own.
        Map<String, String> supplied = new HashMap<>(options.headers());
        supplied.keySet().removeIf(name -> name.equalsIgnoreCase("x-api-key"));
        this.headers = Map.copyOf(supplied);
        this.timeout = options.timeout();
        this.http = options.httpClient() != null
                ? options.httpClient()
                : HttpClient.newBuilder().connectTimeout(options.timeout()).build();
    }

    public String baseUrl() {
        return baseUrl;
    }

    /** Never prints the key. */
    @Override
    public String toString() {
        return "Transport(baseUrl=" + baseUrl + ", apiKey=***)";
    }

    /** Substitutes the path parameters, leaving a path relative to the base URL. */
    public static String resolvePath(String path, Map<String, String> pathParams) {
        String resolved = path;
        for (Map.Entry<String, String> entry : pathParams.entrySet()) {
            String value = entry.getValue();
            if (value == null || value.isEmpty()) {
                throw new IllegalArgumentException(
                        entry.getKey() + " is required and must not be empty.");
            }
            resolved = resolved.replace("{" + entry.getKey() + "}", encode(value));
        }
        return resolved;
    }

    static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    static String buildQuery(List<Map.Entry<String, String>> pairs) {
        if (pairs.isEmpty()) {
            return "";
        }
        StringBuilder out = new StringBuilder("?");
        for (int index = 0; index < pairs.size(); index++) {
            if (index > 0) {
                out.append('&');
            }
            out.append(encode(pairs.get(index).getKey()))
                    .append('=')
                    .append(encode(pairs.get(index).getValue()));
        }
        return out.toString();
    }

    static long backoffMillis(int attempt, HttpResponse<?> response) {
        if (response != null) {
            String header = response.headers().firstValue("retry-after").orElse(null);
            if (header != null) {
                try {
                    double seconds = Double.parseDouble(header);
                    if (seconds >= 0) {
                        return (long) Math.min(seconds * 1000, 60_000);
                    }
                } catch (NumberFormatException ignored) {
                    // Fall through to the exponential curve.
                }
            }
        }
        double ceiling = Math.min(MAX_BACKOFF_MILLIS, 500d * Math.pow(2, attempt));
        return (long) (ceiling * (0.5 + ThreadLocalRandom.current().nextDouble() / 2));
    }

    private boolean shouldRetry(String method, HttpResponse<?> response) {
        if (!RETRY_SAFE_METHODS.contains(method) && !retryWrites) {
            return false;
        }
        return response == null || RETRY_STATUSES.contains(response.statusCode());
    }

    /** Send a request and decode the envelope, retrying where it is safe to. */
    public <T> Envelope<T> send(
            String method,
            String path,
            List<Map.Entry<String, String>> query,
            Object body,
            Class<T> item) {
        URI uri = URI.create(baseUrl + path + buildQuery(query == null ? List.of() : query));
        RuntimeException last = null;

        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            HttpResponse<String> response = null;
            try {
                HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                        .timeout(timeout)
                        .header("accept", "application/json")
                        .header("user-agent", "zelf-java/" + ZelfClient.VERSION);
                headers.forEach(builder::header);
                // Last, so the client's own key always wins.
                builder.header("x-api-key", apiKey);
                if (body == null) {
                    builder.method(method, HttpRequest.BodyPublishers.noBody());
                } else {
                    builder.header("content-type", "application/json");
                    builder.method(method, HttpRequest.BodyPublishers.ofString(writeJson(body)));
                }

                response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() < 400) {
                    return decode(response, item);
                }
                last = ZelfException.fromResponse(response.statusCode(), response.body());
            } catch (HttpTimeoutException error) {
                last = new ZelfException.Timeout();
            } catch (IOException error) {
                last = new ZelfException.Connection(error.getMessage(), error);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new ZelfException.Connection("The request was interrupted.", error);
            }

            if (attempt == maxRetries || !shouldRetry(method, response)) {
                break;
            }
            try {
                Thread.sleep(backoffMillis(attempt, response));
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new ZelfException.Connection("The retry wait was interrupted.", error);
            }
        }
        throw last != null ? last : new ZelfException.Connection("The request was never sent.", null);
    }

    private static String writeJson(Object body) {
        try {
            return MAPPER.writeValueAsString(body);
        } catch (com.fasterxml.jackson.core.JsonProcessingException error) {
            throw new IllegalArgumentException("The request body could not be serialised.", error);
        }
    }

    private static <T> Envelope<T> decode(HttpResponse<String> response, Class<T> item) {
        String raw = response.body();
        if (response.statusCode() == 204 || raw == null || raw.isBlank()) {
            return new Envelope<>("", "", List.of(), 0, 0, null, null, null);
        }
        try {
            JavaType type = MAPPER.getTypeFactory().constructParametricType(Envelope.class, item);
            return MAPPER.readValue(raw, type);
        } catch (IOException error) {
            throw new ZelfException.Api(
                    "The API returned a response that is not a valid envelope.",
                    response.statusCode(), null, null, null);
        }
    }

    static List<Map.Entry<String, String>> newQuery() {
        return new ArrayList<>();
    }
}
