package com.hellozelf.webhooks;

import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Verify a delivery once, then route it to the listener for its type.
 *
 * <p>Framework agnostic: hand it the raw body and the signature header from
 * whatever server is in front of it.
 */
public final class WebhookHandler {

    private final List<String> secrets;
    private final Webhook.Options options;
    private final Map<EventType, List<Consumer<WebhookEvent>>> listeners =
            new EnumMap<>(EventType.class);
    private Consumer<WebhookEvent> fallback;

    public WebhookHandler(List<String> secrets, Webhook.Options options) {
        this.secrets = List.copyOf(secrets);
        this.options = options == null ? Webhook.Options.defaults() : options;
    }

    /** Register a listener for one or more event types. */
    public WebhookHandler on(Consumer<WebhookEvent> listener, EventType... eventTypes) {
        if (eventTypes.length == 0) {
            throw new IllegalArgumentException("Pass at least one event type to listen for.");
        }
        for (EventType name : eventTypes) {
            listeners.computeIfAbsent(name, key -> new ArrayList<>()).add(listener);
        }
        return this;
    }

    /** Register the listener used when no type specific one matched. */
    public WebhookHandler onAny(Consumer<WebhookEvent> listener) {
        this.fallback = listener;
        return this;
    }

    /**
     * Verify, then call every listener registered for the event type. Throws
     * before any listener runs if the delivery does not check out.
     */
    public WebhookEvent handle(byte[] payload, String signature) {
        WebhookEvent event = Webhook.parse(payload, signature, secrets, options);
        EventType kind = event.kind();
        List<Consumer<WebhookEvent>> found = kind == null ? null : listeners.get(kind);
        if (found == null || found.isEmpty()) {
            if (fallback != null) {
                fallback.accept(event);
            }
            return event;
        }
        for (Consumer<WebhookEvent> listener : found) {
            listener.accept(event);
        }
        return event;
    }
}
