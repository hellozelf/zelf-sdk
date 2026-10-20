package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.hellozelf.model.Content;
import com.hellozelf.resources.ContentListParams;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Drives the sandbox. Run with `mvn verify`; surefire excludes it. */
class SandboxIT {

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isEmpty() ? fallback : value;
    }

    private static final String BASE = env("ZELF_BASE_URL", "https://sandbox-api.hellozelf.com");
    private static final String KEY = env("ZELF_API_KEY", "sk_zelf_sandbox_demo");

    private ZelfClient client() {
        return new ZelfClient(new ZelfClientOptions().apiKey(KEY).baseUrl(BASE));
    }

    @Test
    void usageDecodes() {
        assertNotNull(client().usage().retrieve());
    }

    @Test
    void aPageDecodesEveryRow() {
        Page<Content> page = client().content().list(new ContentListParams().pageSize(2L));
        assertEquals(2, page.itemCount());
        for (Content row : page.results()) {
            assertTrue(row.id().startsWith("con_"), row.id());
        }
    }

    @Test
    void autoPagingStopsAtTheBound() {
        Page<Content> page = client().content().list(new ContentListParams().pageSize(2L));
        List<Content> rows = new ArrayList<>();
        page.autoPaging(PageLimits.pages(2), rows::add);
        assertEquals(4, rows.size());
    }

    @Test
    void aBadKeyRaisesTheTypedError() {
        ZelfClient bad = new ZelfClient(
                new ZelfClientOptions().apiKey("sk_zelf_" + "9".repeat(64)).baseUrl(BASE).maxRetries(0));
        ZelfException.Api error =
                assertThrows(ZelfException.Api.class, () -> bad.usage().retrieve());
        assertEquals(401, error.status());
        assertEquals("INVALID_API_KEY", error.code());
    }

    @Test
    void aRateLimitIsRetriedThenSurfaced() {
        ZelfClient throttled = new ZelfClient(new ZelfClientOptions()
                .apiKey(KEY)
                .baseUrl(BASE)
                .maxRetries(1)
                .header("x-sandbox-force-error", "RATE_LIMIT_EXCEEDED"));
        ZelfException.Api error =
                assertThrows(ZelfException.Api.class, () -> throttled.usage().retrieve());
        assertEquals(429, error.status());
    }

    @Test
    void eventTypesAreListed() {
        assertFalse(client().webhooks().listEvents().isEmpty());
    }
}
