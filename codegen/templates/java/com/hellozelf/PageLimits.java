package com.hellozelf;

/** Bounds how far a walk over the remaining pages goes. */
public record PageLimits(Integer maxPages, Integer maxItems) {

    /** Walk everything. */
    public static PageLimits none() {
        return new PageLimits(null, null);
    }

    /**
     * Stop after {@code count} pages, counting the one already in hand. A
     * value of 1 makes no further request.
     */
    public static PageLimits pages(int count) {
        return new PageLimits(count, null);
    }

    /**
     * Stop once {@code count} items have been visited, so no page is requested
     * that is not needed to reach the count.
     */
    public static PageLimits items(int count) {
        return new PageLimits(null, count);
    }

    public PageLimits withMaxPages(int count) {
        return new PageLimits(count, maxItems);
    }

    public PageLimits withMaxItems(int count) {
        return new PageLimits(maxPages, count);
    }

    void validate() {
        if ((maxPages != null && maxPages < 1) || (maxItems != null && maxItems < 1)) {
            throw new IllegalArgumentException("maxPages and maxItems need a value of 1 or greater.");
        }
    }
}
