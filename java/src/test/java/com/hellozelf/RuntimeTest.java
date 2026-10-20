package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.hellozelf.model.Brand;
import com.hellozelf.resources.BrandsListParams;
import java.io.IOException;
import java.net.http.HttpClient;
import java.util.List;
import org.junit.jupiter.api.Test;

/** The hand written runtime: options, transport, paging and errors. */
class RuntimeTest {

    private static final String KEY = "sk_zelf_" + "0".repeat(64);
    private static final String ROW =
            "{\"id\":\"brd_1\",\"title\":\"ZelfAI\",\"is_primary\":true,\"keywords\":{}}";

    private static String envelope(String results, String next) {
        return "{\"log_id\":\"log_1\",\"timestamp\":\"2026-01-01T00:00:00Z\","
                + "\"applied_filters\":{\"page\":1},\"results\":[" + results + "],"
                + "\"item_count\":1,\"page\":1,\"next\":" + next + ",\"previous\":null}";
    }

    private static ZelfClient clientFor(Stub stub, int retries) {
        return new ZelfClient(new ZelfClientOptions()
                .apiKey(KEY)
                .baseUrl(stub.baseUrl())
                .maxRetries(retries));
    }

    @Test
    void negativeRetriesAreRefused() {
        assertThrows(IllegalArgumentException.class,
                () -> new ZelfClient(new ZelfClientOptions().apiKey(KEY).maxRetries(-1)));
    }

    @Test
    void optionsCarryTimeoutHeadersAndHttpClient() {
        ZelfClientOptions options = new ZelfClientOptions()
                .apiKey(KEY)
                .timeout(java.time.Duration.ofSeconds(5))
                .retryWrites(true)
                .header("X-Trace", "abc")
                .httpClient(HttpClient.newHttpClient());

        assertEquals(java.time.Duration.ofSeconds(5), options.timeout());
        assertTrue(options.retryWrites());
        assertEquals("abc", options.headers().get("X-Trace"));
        assertNotNull(options.httpClient());
    }

    @Test
    void theTransportHidesTheKey() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(envelope(ROW, "null")))) {
            ZelfClient client = clientFor(stub, 0);
            String shown = client.toString() + client.content().toString();
            assertFalse(shown.contains(KEY));
        }
    }

    @Test
    void aPageExposesItsEnvelope() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(envelope(ROW, "2")))) {
            Page<Brand> page = clientFor(stub, 0).brands().list(new BrandsListParams());

            assertEquals(1, page.itemCount());
            assertEquals(1, page.page());
            assertEquals(2, page.next());
            assertNull(page.previous());
            assertNotNull(page.appliedFilters());
            assertEquals("log_1", page.logId());
            assertTrue(page.hasNext());
            assertTrue(page.iterator().hasNext());
            assertTrue(page.toString().contains("Page("));
            for (Brand row : page) {
                assertEquals("ZelfAI", row.title());
            }
        }
    }

    @Test
    void pageLimitsAreImmutable() {
        PageLimits limits = PageLimits.none().withMaxPages(3).withMaxItems(10);
        assertEquals(3, limits.maxPages());
        assertEquals(10, limits.maxItems());
    }

    @Test
    void aRetryableStatusIsRetriedAndRetryAfterHonoured() throws IOException {
        try (Stub stub = new Stub((index, call) -> index == 1
                ? new Stub.Reply(503, "{\"error\":{\"code\":\"SERVICE_UNAVAILABLE\"}}", "0")
                : Stub.Reply.ok(envelope(ROW, "null")))) {
            clientFor(stub, 1).brands().list(new BrandsListParams());
            assertEquals(2, stub.calls().size());
        }
    }

    @Test
    void thePageAfterThisOneKeepsTheOriginalFilters() throws IOException {
        // Every filter has to ride along to page two, or page two answers a
        // different question than page one did.
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(
                envelope(ROW, index == 1 ? "2" : "null")))) {
            Page<com.hellozelf.model.Content> page = clientFor(stub, 0).content()
                    .list(new com.hellozelf.resources.ContentListParams().brandId("brd_1"));

            assertNotNull(page.nextPage());
            String second = stub.calls().get(1).query();
            assertTrue(second.contains("brand_id=brd_1"), second);
            assertTrue(second.contains("page=2"), second);
        }
    }

    @Test
    void anUnparseableRetryAfterFallsBackToBackoff() throws IOException {
        try (Stub stub = new Stub((index, call) -> index == 1
                ? new Stub.Reply(500, "{\"error\":{\"code\":\"INTERNAL_ERROR\"}}", "soon")
                : Stub.Reply.ok(envelope(ROW, "null")))) {
            clientFor(stub, 1).brands().list(new BrandsListParams());
            assertEquals(2, stub.calls().size());
        }
    }

    @Test
    void aConnectionFailureIsTyped() {
        ZelfClient client = new ZelfClient(new ZelfClientOptions()
                .apiKey(KEY)
                .baseUrl("http://127.0.0.1:1")
                .maxRetries(0));
        assertThrows(ZelfException.Connection.class,
                () -> client.brands().list(new BrandsListParams()));
    }

    @Test
    void aTimeoutIsTyped() throws IOException {
        try (Stub stub = new Stub((index, call) -> {
            try {
                Thread.sleep(300);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            return Stub.Reply.ok(envelope(ROW, "null"));
        })) {
            ZelfClient client = new ZelfClient(new ZelfClientOptions()
                    .apiKey(KEY)
                    .baseUrl(stub.baseUrl())
                    .timeout(java.time.Duration.ofMillis(50))
                    .maxRetries(0));
            assertThrows(ZelfException.Timeout.class,
                    () -> client.brands().list(new BrandsListParams()));
        }
    }

    @Test
    void anEmptyBodyDecodesToAnEmptyEnvelope() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(""))) {
            assertThrows(ZelfException.NotFound.class,
                    () -> clientFor(stub, 0).usage().retrieve());
        }
    }

    @Test
    void aBodyThatIsNotJsonIsReported() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok("<html>"))) {
            assertThrows(ZelfException.Api.class, () -> clientFor(stub, 0).usage().retrieve());
        }
    }

    @Test
    void anErrorBodyThatIsNotJsonStillRaises() throws IOException {
        try (Stub stub = new Stub((index, call) -> new Stub.Reply(500, "<html>", null))) {
            assertThrows(ZelfException.Api.class, () -> clientFor(stub, 0).usage().retrieve());
        }
    }

    @Test
    void everyStatusMapsToItsSubclass() throws IOException {
        List<Integer> statuses = List.of(400, 401, 403, 404, 406, 409, 429, 500, 503);
        for (int status : statuses) {
            try (Stub stub = new Stub((index, call) -> new Stub.Reply(
                    status, "{\"log_id\":\"log_1\",\"error\":{\"code\":\"X\",\"message\":\"m\","
                            + "\"details\":{\"field\":\"bad\"}}}", null))) {
                ZelfException.Api error = assertThrows(ZelfException.Api.class,
                        () -> clientFor(stub, 0).usage().retrieve());
                assertEquals(status, error.status());
                assertNotNull(error.details());
                assertTrue(error.toString().contains("log_id=log_1"));
            }
        }
    }

    @Test
    void connectionAndTimeoutErrorsPrint() {
        ZelfException.Connection connection =
                new ZelfException.Connection("socket closed", new IOException("boom"));
        assertTrue(connection.getMessage().contains("socket closed"));
        assertNotNull(new ZelfException.Timeout().getMessage());
    }

    @Test
    void anApiErrorWithoutALogIdStillPrints() {
        ZelfException.Api error = new ZelfException.Api("m", 500, null, null, null);
        assertFalse(error.toString().contains("log_id"));
    }

    @Test
    void aSuppliedHttpClientIsUsed() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(envelope(ROW, "null")))) {
            ZelfClient client = new ZelfClient(new ZelfClientOptions()
                    .apiKey(KEY)
                    .baseUrl(stub.baseUrl())
                    .httpClient(HttpClient.newHttpClient()));
            client.brands().list(new BrandsListParams());
            assertEquals(1, stub.calls().size());
        }
    }

    @Test
    void optionsAndTransportHideTheKeyInToString() {
        ZelfClientOptions options = new ZelfClientOptions().apiKey(KEY).baseUrl("https://x");
        assertFalse(options.toString().contains(KEY));
        assertTrue(options.toString().contains("apiKey=***"));
        assertFalse(new Transport(options).toString().contains(KEY));
    }

    @Test
    void anUnserialisableBodyIsRefused() {
        ZelfClientOptions options = new ZelfClientOptions().apiKey(KEY).baseUrl("https://x");
        Transport transport = new Transport(options);
        assertThrows(IllegalArgumentException.class, () -> transport.send(
                "POST", "/api/v1/usage/", Transport.newQuery(), new Object() {
                    @SuppressWarnings("unused")
                    public Object getSelf() {
                        throw new UnsupportedOperationException("not serialisable");
                    }
                }, Object.class));
    }

    @Test
    void anUnmappedStatusFallsBackToTheBaseApiError() throws IOException {
        try (Stub stub = new Stub((index, call) -> new Stub.Reply(
                418, "{\"error\":{\"code\":\"TEAPOT\",\"message\":\"no coffee\"}}", null))) {
            ZelfException.Api error = assertThrows(ZelfException.Api.class,
                    () -> clientFor(stub, 0).usage().retrieve());
            assertEquals(418, error.status());
        }
    }

    @Test
    void anInterruptedRequestIsTyped() throws IOException {
        try (Stub stub = new Stub((index, call) -> Stub.Reply.ok(envelope(ROW, "null")))) {
            ZelfClient client = clientFor(stub, 0);
            Thread.currentThread().interrupt();
            try {
                assertThrows(ZelfException.Connection.class,
                        () -> client.brands().list(new BrandsListParams()));
            } finally {
                Thread.interrupted();
            }
        }
    }

    @Test
    void anInterruptedRetryWaitIsTyped() throws IOException {
        try (Stub stub = new Stub((index, call) -> new Stub.Reply(
                503, "{\"error\":{\"code\":\"SERVICE_UNAVAILABLE\"}}", "5"))) {
            ZelfClient client = clientFor(stub, 2);
            Thread thread = new Thread(() -> assertThrows(ZelfException.Connection.class,
                    () -> client.brands().list(new BrandsListParams())));
            thread.start();
            try {
                Thread.sleep(80);
                thread.interrupt();
                thread.join(5000);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
