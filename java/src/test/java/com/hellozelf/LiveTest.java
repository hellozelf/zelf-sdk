package com.hellozelf;

import com.hellozelf.model.Content;
import com.hellozelf.resources.BrandAccountsListParams;
import com.hellozelf.resources.ContentDetailsParams;
import com.hellozelf.resources.ContentListParams;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Drives the real API. Skipped unless ZELF_API_KEY is set. */
@EnabledIfEnvironmentVariable(named = "ZELF_API_KEY", matches = ".+")
class LiveTest {

    private static final String BRAND = "brd_6u599tNI2jemKDcb";

    private static ContentListParams scope() {
        return new ContentListParams()
                .brandId(BRAND)
                .postedWithinDays(365L)
                .viewCountMin(250000000L)
                .pageSize(3L);
    }

    private static void check(String name, Supplier<String> body) {
        long started = System.currentTimeMillis();
        String status = "PASS";
        String detail;
        try {
            detail = body.get();
        } catch (RuntimeException error) {
            status = "FAIL";
            detail = error.getClass().getSimpleName() + ": " + error.getMessage();
        }
        if (detail.length() > 90) {
            detail = detail.substring(0, 90);
        }
        System.out.printf("%-34s %s  %6dms  %s%n",
                name, status, System.currentTimeMillis() - started, detail);
    }

    @Test
    void sweep() {
        ZelfClient client = new ZelfClient(System.getenv("ZELF_API_KEY"));

        check("usage.retrieve", () -> "usage ok " + client.usage().retrieve().getClass().getSimpleName());
        check("content.list", () -> {
            Page<Content> page = client.content().list(scope());
            return "items=" + page.itemCount() + " first=" + page.results().get(0).id()
                    + " views=" + page.results().get(0).viewCount();
        });
        check("content.list autoPaging pages(2)", () -> {
            List<String> ids = new ArrayList<>();
            client.content().list(scope()).autoPaging(PageLimits.pages(2), item -> ids.add(item.id()));
            return "walked " + ids.size() + " across <=2 pages";
        });
        check("content.details", () -> {
            Page<Content> page = client.content().list(scope());
            Content found = client.content()
                    .details(page.results().get(0).id(), new ContentDetailsParams().brandId(BRAND));
            return "id=" + found.id() + " platform=" + found.platform();
        });
        check("content.details (missing)", () -> {
            try {
                client.content().details("con_J64wsBXg9rmhOE6dFX", null);
                return "no error raised";
            } catch (ZelfException.Api error) {
                return "Api status=" + error.status() + " code=" + error.code();
            }
        });
        check("bad key -> 401 typed", () -> {
            ZelfClient bad = new ZelfClient(
                    ZelfClientOptions.builder().apiKey("sk_zelf_definitely_invalid").maxRetries(0));
            try {
                bad.usage().retrieve();
                return "no error raised";
            } catch (ZelfException.Api error) {
                return error.status() + " " + error.code();
            }
        });
        check("brands.list", () -> "brands=" + client.brands().list(null).itemCount());
        check("webhooks.list_events", () -> "events=" + client.webhooks().listEvents().size());
        check("brand_accounts.list", () -> {
            var groups = client.brandAccounts().list(
                    new BrandAccountsListParams().brandId(BRAND).accountType("tracked"));
            var tracked = groups.tracked() == null ? 0 : groups.tracked().size();
            return "tracked=" + tracked;
        });
    }
}
