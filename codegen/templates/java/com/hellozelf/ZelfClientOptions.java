package com.hellozelf;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/** Settings for a {@link ZelfClient}. Build one with {@link #builder()}. */
public final class ZelfClientOptions {

    private String apiKey;
    private String baseUrl = baseUrlFromEnvironment();

    private static String baseUrlFromEnvironment() {
        String url = System.getenv(Transport.BASE_URL_ENV);
        return url == null || url.isEmpty() ? Transport.DEFAULT_BASE_URL : url;
    }
    private Duration timeout = Duration.ofSeconds(60);
    private int maxRetries = 2;
    private boolean retryWrites;
    private final Map<String, String> headers = new HashMap<>();
    private HttpClient httpClient;

    public static ZelfClientOptions builder() {
        return new ZelfClientOptions();
    }

    /** The brand API key. Falls back to ZELF_API_KEY. */
    public ZelfClientOptions apiKey(String value) {
        this.apiKey = value;
        return this;
    }

    public ZelfClientOptions baseUrl(String value) {
        this.baseUrl = value;
        return this;
    }

    public ZelfClientOptions timeout(Duration value) {
        this.timeout = value;
        return this;
    }

    public ZelfClientOptions maxRetries(int value) {
        this.maxRetries = value;
        return this;
    }

    /**
     * Allows non-idempotent requests to be retried. The API publishes no
     * idempotency key, so a retried create can run twice. Opt in deliberately.
     */
    public ZelfClientOptions retryWrites(boolean value) {
        this.retryWrites = value;
        return this;
    }

    public ZelfClientOptions header(String name, String value) {
        this.headers.put(name, value);
        return this;
    }

    public ZelfClientOptions httpClient(HttpClient value) {
        this.httpClient = value;
        return this;
    }

    public String apiKey() {
        return apiKey;
    }

    public String baseUrl() {
        return baseUrl;
    }

    public Duration timeout() {
        return timeout;
    }

    public int maxRetries() {
        return maxRetries;
    }

    public boolean retryWrites() {
        return retryWrites;
    }

    public Map<String, String> headers() {
        return headers;
    }

    public HttpClient httpClient() {
        return httpClient;
    }

    /** Never prints the key. */
    @Override
    public String toString() {
        return "ZelfClientOptions(baseUrl=" + baseUrl + ", apiKey=***)";
    }
}
