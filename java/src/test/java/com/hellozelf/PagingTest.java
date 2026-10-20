package com.hellozelf;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.hellozelf.model.Content;
import com.hellozelf.resources.ContentListParams;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class PagingTest {

    /** Serves `count` pages of one row each. */
    private static Stub paged(int count) throws IOException {
        return new Stub((n, call) -> {
            String next = n < count ? String.valueOf(n + 1) : "null";
            return Stub.Reply.ok(
                    Fixtures.envelope("[" + Fixtures.contentRow("con_" + n) + "]", n, next));
        });
    }

    private static List<String> ids(Page<Content> page, PageLimits limits) {
        List<String> out = new ArrayList<>();
        page.autoPaging(limits, item -> out.add(item.id()));
        return out;
    }

    @Test
    void maxPagesStopsTheWalkEarly() throws IOException {
        try (Stub stub = paged(5)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertEquals(List.of("con_1", "con_2", "con_3"), ids(page, PageLimits.pages(3)));
            assertEquals(3, stub.calls().size());
        }
    }

    @Test
    void maxPagesOfOneMakesNoFurtherRequest() throws IOException {
        try (Stub stub = paged(5)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertEquals(List.of("con_1"), ids(page, PageLimits.pages(1)));
            assertEquals(1, stub.calls().size());
        }
    }

    @Test
    void maxItemsStopsBeforeAPageItDoesNotNeed() throws IOException {
        try (Stub stub = paged(5)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertEquals(List.of("con_1", "con_2"), ids(page, PageLimits.items(2)));
            assertEquals(2, stub.calls().size());
        }
    }

    @Test
    void noLimitWalksEverything() throws IOException {
        try (Stub stub = paged(4)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertEquals(List.of("con_1", "con_2", "con_3", "con_4"), ids(page, PageLimits.none()));
            assertEquals(4, stub.calls().size());
        }
    }

    @Test
    void pagesHonoursMaxPages() throws IOException {
        try (Stub stub = paged(5)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            List<Integer> numbers = page.pages(PageLimits.pages(2)).stream().map(Page::page).toList();

            assertEquals(List.of(1, 2), numbers);
            assertEquals(2, stub.calls().size());
        }
    }

    @Test
    void aLimitBelowOneIsRejected() throws IOException {
        try (Stub stub = paged(3)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertThrows(IllegalArgumentException.class,
                    () -> page.collectAll(PageLimits.pages(0)));
            assertThrows(IllegalArgumentException.class,
                    () -> page.collectAll(PageLimits.items(0)));
        }
    }

    @Test
    void collectAllGathersEveryItem() throws IOException {
        try (Stub stub = paged(3)) {
            Page<Content> page = stub.client(0).content().list(new ContentListParams());

            assertEquals(3, page.collectAll(PageLimits.none()).size());
        }
    }
}
