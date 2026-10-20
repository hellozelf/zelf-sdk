package com.hellozelf;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BiFunction;

/**
 * A stub API built on the JDK's own HttpServer, so the suite needs no mocking
 * library.
 */
public final class Stub implements AutoCloseable {

    /** One recorded request. */
    public record Call(String method, String path, String query, String body,
            java.net.http.HttpHeaders headers) {
    }

    /** The answer for the nth request. */
    public record Reply(int status, String body, String retryAfter) {
        public static Reply ok(String body) {
            return new Reply(200, body, null);
        }
    }

    private final HttpServer server;
    private final List<Call> calls = new ArrayList<>();
    private final List<com.sun.net.httpserver.Headers> rawHeaders = new ArrayList<>();

    public Stub(BiFunction<Integer, Call, Reply> responder) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> handle(exchange, responder));
        server.setExecutor(null);
        server.start();
    }

    private void handle(HttpExchange exchange, BiFunction<Integer, Call, Reply> responder)
            throws IOException {
        String body;
        try (InputStream stream = exchange.getRequestBody()) {
            body = new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
        Call call = new Call(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getRawPath(),
                exchange.getRequestURI().getRawQuery(),
                body,
                null);
        calls.add(call);
        rawHeaders.add(exchange.getRequestHeaders());

        Reply reply = responder.apply(calls.size(), call);
        byte[] payload = reply.body().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        if (reply.retryAfter() != null) {
            exchange.getResponseHeaders().add("Retry-After", reply.retryAfter());
        }
        exchange.sendResponseHeaders(reply.status(), payload.length);
        exchange.getResponseBody().write(payload);
        exchange.close();
    }

    public String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    public List<Call> calls() {
        return calls;
    }

    public String header(int index, String name) {
        return rawHeaders.get(index).getFirst(name);
    }

    /** Every value sent under one header name, so a duplicate is visible. */
    public List<String> headers(int index, String name) {
        List<String> values = rawHeaders.get(index).get(name);
        return values == null ? List.of() : values;
    }

    public ZelfClient client(int maxRetries) {
        return new ZelfClient(ZelfClientOptions.builder()
                .apiKey(Fixtures.API_KEY)
                .baseUrl(baseUrl())
                .maxRetries(maxRetries));
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
