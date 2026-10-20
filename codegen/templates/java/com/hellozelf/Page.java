package com.hellozelf;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * One page of results, plus the envelope metadata that came with it.
 *
 * <p>The page keeps the request that produced it, so the next page is fetched
 * by re-issuing that request with a new {@code page} value.
 */
public final class Page<T> implements Iterable<T> {

    private final List<T> results;
    private final String logId;
    private final int page;
    private final int itemCount;
    private final Integer next;
    private final Integer previous;
    private final JsonNode appliedFilters;

    private final Transport transport;
    private final String path;
    private final List<Map.Entry<String, String>> query;
    private final Class<T> item;

    /** Built by the resource classes; not part of the surface callers use. */
    public Page(Envelope<T> envelope, Transport transport, String path,
            List<Map.Entry<String, String>> query, Class<T> item) {
        this.results = envelope.results();
        this.logId = envelope.logId();
        this.page = envelope.page();
        this.itemCount = envelope.itemCount();
        this.next = envelope.next();
        this.previous = envelope.previous();
        this.appliedFilters = envelope.appliedFilters();
        this.transport = transport;
        this.path = path;
        this.query = query;
        this.item = item;
    }

    public List<T> results() {
        return results;
    }

    public String logId() {
        return logId;
    }

    public int page() {
        return page;
    }

    public int itemCount() {
        return itemCount;
    }

    public Integer next() {
        return next;
    }

    public Integer previous() {
        return previous;
    }

    public JsonNode appliedFilters() {
        return appliedFilters;
    }

    public boolean hasNext() {
        return next != null;
    }

    @Override
    public java.util.Iterator<T> iterator() {
        return results.iterator();
    }

    @Override
    public String toString() {
        return "Page(page=" + page + ", itemCount=" + itemCount + ", hasNext=" + hasNext() + ")";
    }

    /** The page after this one, or null when there is none. */
    public Page<T> nextPage() {
        if (next == null) {
            return null;
        }
        List<Map.Entry<String, String>> carried = new ArrayList<>();
        for (Map.Entry<String, String> pair : query) {
            if (!pair.getKey().equals("page")) {
                carried.add(pair);
            }
        }
        carried.add(Map.entry("page", String.valueOf(next)));
        Envelope<T> envelope = transport.send("GET", path, carried, null, item);
        return new Page<>(envelope, transport, path, carried, item);
    }

    /**
     * Walk the remaining pages, handing each item to {@code visit}.
     *
     * <p>{@link PageLimits#maxPages} bounds how many pages are fetched and
     * {@link PageLimits#maxItems} how many items come back. Either one stops
     * the walk, so no page is requested once enough items are in hand.
     */
    public void autoPaging(PageLimits limits, Consumer<T> visit) {
        PageLimits bounds = limits == null ? PageLimits.none() : limits;
        bounds.validate();
        int pagesSeen = 0;
        int itemsSeen = 0;
        Page<T> current = this;
        while (current != null) {
            for (T row : current.results) {
                visit.accept(row);
                itemsSeen++;
                if (bounds.maxItems() != null && itemsSeen >= bounds.maxItems()) {
                    return;
                }
            }
            pagesSeen++;
            if (bounds.maxPages() != null && pagesSeen >= bounds.maxPages()) {
                return;
            }
            current = current.nextPage();
        }
    }

    /** Walk the remaining pages and collect every item into one list. */
    public List<T> collectAll(PageLimits limits) {
        List<T> out = new ArrayList<>();
        autoPaging(limits, out::add);
        return out;
    }

    /** Yield this page and the ones after it. */
    public List<Page<T>> pages(PageLimits limits) {
        PageLimits bounds = limits == null ? PageLimits.none() : limits;
        bounds.validate();
        List<Page<T>> out = new ArrayList<>();
        Page<T> current = this;
        while (current != null) {
            out.add(current);
            if (bounds.maxPages() != null && out.size() >= bounds.maxPages()) {
                break;
            }
            current = current.nextPage();
        }
        return out;
    }
}
