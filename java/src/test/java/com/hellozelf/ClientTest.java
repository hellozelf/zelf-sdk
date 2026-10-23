package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.hellozelf.model.Content;
import com.hellozelf.resources.ContentListParams;
import com.hellozelf.resources.CreatorSyncCreateParams;
import java.io.IOException;
import java.util.List;
import org.junit.jupiter.api.Test;

class ClientTest {

    @Test
    void listReturnsATypedPage() throws IOException {
        String body = Fixtures.envelope("[" + Fixtures.contentRow("con_1") + "]");
        try (Stub stub = new Stub((n, call) -> Stub.Reply.ok(body))) {
            ZelfClient client = stub.client(0);

            Page<Content> page = client.content().list(new ContentListParams().search("running shoes"));

            assertEquals(1, page.results().size());
            assertEquals("con_1", page.results().get(0).id());
            assertEquals(184230L, page.results().get(0).viewCount());
            assertEquals("log_1", page.logId());
            assertFalse(page.hasNext());
            assertTrue(stub.calls().get(0).query().contains("search=running%20shoes"));
        }
    }

    @Test
    void theApiKeyTravelsInAHeaderNeverTheUrl() throws IOException {
        try (Stub stub = new Stub((n, call) -> Stub.Reply.ok(Fixtures.envelope("[{\"plan\":\"pro\"}]")))) {
            stub.client(0).usage().retrieve();

            assertEquals(Fixtures.API_KEY, stub.header(0, "x-api-key"));
            assertFalse(stub.calls().get(0).path().contains(Fixtures.API_KEY));
            assertTrue(stub.header(0, "user-agent").startsWith("zelf-java/"));
        }
    }

    @Test
    void theApiKeyStaysOutOfToString() {
        ZelfClient client = new ZelfClient(Fixtures.API_KEY);

        assertFalse(client.toString().contains(Fixtures.API_KEY));
        assertTrue(client.toString().contains("***"));
    }

    @Test
    void aMissingKeyFailsBeforeAnyRequest() {
        assertThrows(IllegalArgumentException.class,
                () -> new ZelfClient(ZelfClientOptions.builder().apiKey("")));
    }

    @Test
    void aSingleReadThatMatchesNothingIsANotFound() throws IOException {
        try (Stub stub = new Stub((n, call) -> Stub.Reply.ok(Fixtures.envelope("[]")))) {
            ZelfClient client = stub.client(0);

            ZelfException.Api error = assertThrows(ZelfException.NotFound.class,
                    () -> client.content().details("con_missing", null));

            assertEquals(404, error.status());
        }
    }

    @Test
    void pathParametersAreEscaped() throws IOException {
        String body = Fixtures.envelope("[" + Fixtures.contentRow("con_1") + "]");
        try (Stub stub = new Stub((n, call) -> Stub.Reply.ok(body))) {
            stub.client(0).content().details("con/../../admin", null);

            assertTrue(stub.calls().get(0).path().contains("con%2F..%2F..%2Fadmin"));
        }
    }

    @Test
    void anEmptyPathParameterIsRejected() {
        ZelfClient client = new ZelfClient(Fixtures.API_KEY);

        assertThrows(IllegalArgumentException.class, () -> client.content().details("", null));
    }

    @Test
    void errorsMapToTypedClasses() throws IOException {
        String body = "{\"log_id\":\"log_1\",\"error\":{\"code\":\"INVALID_API_KEY\","
                + "\"message\":\"Nope.\",\"details\":{}}}";
        try (Stub stub = new Stub((n, call) -> new Stub.Reply(401, body, null))) {
            ZelfClient client = stub.client(0);

            ZelfException.Api error = assertThrows(ZelfException.Authentication.class,
                    () -> client.content().list(new ContentListParams()));

            assertEquals(401, error.status());
            assertEquals(ZelfErrorCode.INVALID_API_KEY, error.code());
            assertEquals("log_1", error.logId());
        }
    }

    @Test
    void aRateLimitedReadIsRetried() throws IOException {
        String ok = Fixtures.envelope("[" + Fixtures.contentRow("con_1") + "]");
        try (Stub stub = new Stub((n, call) -> n == 1
                ? new Stub.Reply(429, "{\"error\":{\"code\":\"RATE_LIMIT_EXCEEDED\"}}", "0")
                : Stub.Reply.ok(ok))) {
            ZelfClient client = stub.client(2);

            Page<Content> page = client.content().list(new ContentListParams());

            assertEquals(1, page.results().size());
            assertEquals(2, stub.calls().size());
        }
    }

    @Test
    void aWriteIsNotRetriedByDefault() throws IOException {
        try (Stub stub = new Stub((n, call) ->
                new Stub.Reply(503, "{\"error\":{\"code\":\"SERVICE_UNAVAILABLE\"}}", null))) {
            ZelfClient client = stub.client(3);

            assertThrows(ZelfException.ServiceUnavailable.class, () -> client.creatorSync()
                    .create(new CreatorSyncCreateParams().profileUrl("https://www.tiktok.com/@zelf")));

            // The API has no idempotency key, so a retried create could run twice.
            assertEquals(1, stub.calls().size());
        }
    }

    @Test
    void aClientErrorIsNeverRetried() throws IOException {
        try (Stub stub = new Stub((n, call) ->
                new Stub.Reply(400, "{\"error\":{\"code\":\"VALIDATION_ERROR\"}}", null))) {
            ZelfClient client = stub.client(3);

            assertThrows(ZelfException.BadRequest.class,
                    () -> client.content().list(new ContentListParams()));

            assertEquals(1, stub.calls().size());
        }
    }

    @Test
    void arrayQueryParametersRepeatTheKey() throws IOException {
        try (Stub stub = new Stub((n, call) -> Stub.Reply.ok(Fixtures.envelope("[]")))) {
            stub.client(0).content().list(new ContentListParams()
                    .platform(List.of("instagram", "tiktok"))
                    .isOwned(true));

            String query = stub.calls().get(0).query();
            assertTrue(query.contains("platform=instagram"));
            assertTrue(query.contains("platform=tiktok"));
            assertTrue(query.contains("is_owned=true"));
            assertFalse(query.contains("brand_id"));
        }
    }

    @Test
    void requestBodiesAreSentAsJson() throws IOException {
        try (Stub stub = new Stub((n, call) ->
                new Stub.Reply(201, Fixtures.envelope("[{\"id\":\"ana_1\"}]"), null))) {
            stub.client(0).aiAnalysis().create(
                    new com.hellozelf.resources.AiAnalysisCreateParams().name("Launch").topic("sentiment"));

            String sent = stub.calls().get(0).body();
            assertTrue(sent.contains("\"name\":\"Launch\""));
            assertTrue(sent.contains("\"topic\":\"sentiment\""));
        }
    }

    // A caller reads the exception, not its details, so the reason belongs there.
    @Test
    void aRefusalNamesTheFieldAndTheLimit() throws IOException {
        String body = "{\"log_id\":\"log_1\",\"error\":{\"code\":\"VALIDATION_ERROR\","
                + "\"message\":\"Request validation failed.\","
                + "\"details\":{\"posted_after\":[\"Must not exceed 366 days.\"]}}}";
        try (Stub stub = new Stub((n, call) -> new Stub.Reply(400, body, null))) {
            ZelfClient client = stub.client(0);

            ZelfException.Api error = assertThrows(ZelfException.BadRequest.class,
                    () -> client.content().list(new ContentListParams()));

            assertEquals("posted_after: Must not exceed 366 days.", error.renderedDetails());
            assertTrue(error.toString().contains("posted_after: Must not exceed 366 days."));
        }
    }

    // The API usually sends a list per field, but one string is just as valid.
    @Test
    void aReasonThatIsNotAListIsPrintedAsItCame() throws IOException {
        String body = "{\"error\":{\"code\":\"VALIDATION_ERROR\",\"message\":\"Bad.\","
                + "\"details\":{\"page\":\"Must be 1 or greater.\"}}}";
        try (Stub stub = new Stub((n, call) -> new Stub.Reply(400, body, null))) {
            ZelfClient client = stub.client(0);

            ZelfException.Api error = assertThrows(ZelfException.BadRequest.class,
                    () -> client.content().list(new ContentListParams()));

            assertEquals("page: Must be 1 or greater.", error.renderedDetails());
        }
    }

    // No details at all leaves the message exactly as the API wrote it.
    @Test
    void aRefusalWithoutDetailsReadsAsItCame() throws IOException {
        String body = "{\"error\":{\"code\":\"VALIDATION_ERROR\",\"message\":\"Bad.\"}}";
        try (Stub stub = new Stub((n, call) -> new Stub.Reply(400, body, null))) {
            ZelfClient client = stub.client(0);

            ZelfException.Api error = assertThrows(ZelfException.BadRequest.class,
                    () -> client.content().list(new ContentListParams()));

            assertEquals("", error.renderedDetails());
        }
    }
}
