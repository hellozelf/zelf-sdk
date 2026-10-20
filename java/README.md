# zelf-sdk (Java)

Official client for the Zelf API. Part of
[hellozelf/zelf-sdk](https://github.com/hellozelf/zelf-sdk), which holds the
same client in eight languages.

## Install

```xml
<dependency>
  <groupId>com.hellozelf</groupId>
  <artifactId>zelf-sdk</artifactId>
  <version>1.0.0</version>
</dependency>
```

```java
import com.hellozelf.ZelfClient;

ZelfClient client = new ZelfClient("sk_zelf_...");
```

Requires Java 17.

## Client options

| Option | Default | What it does |
|---|---|---|
| `.apiKey()` | `ZELF_API_KEY` | Brand API key, sent as `x-api-key` |
| `.baseUrl()` | `ZELF_BASE_URL`, else production | Point at the sandbox or another deployment |
| `.timeout()` | 60s | Bounds each individual attempt, not the whole call |
| `.maxRetries()` | 2 | How many times a retryable response is retried |
| `.retryWrites()` | off | Allow non-idempotent requests to be retried |
| `.header()` | none | Added to every request |
| `.httpClient()` | built in | Supply your own HTTP client |

## Pagination

A list call returns one page. The page carries its rows and the envelope that
came with them.

| On the page | Meaning |
|---|---|
| `results` | the rows, already decoded |
| `item_count` | rows on this page |
| `page` | 1-based page number |
| `next` / `previous` | neighbouring page numbers, or nothing at the ends |
| `applied_filters` | the filters the API actually applied |
| `log_id` | quote this in a support request |

Walking the rest takes one of three bounds: everything, at most N pages, or at
most N items. The item bound never fetches a page it does not need.

```java
Page<Content> page = client.content().list(new ContentListParams().pageSize(50L));

for (Content item : page.results()) { }          // this page only

page.autoPaging(visit);                          // every page
page.autoPaging(PageLimits.pages(5), visit);
page.autoPaging(PageLimits.items(100), visit);
```

Pass options with `new ZelfClient(new ZelfClientOptions()...)`.

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id`.

```java
try {
    client.content().details("con_nope", null);
} catch (ZelfException.NotFound error) {
    System.out.println(error.status() + " " + error.code() + " " + error.logId());
}
```

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server, service unavailable. Network
problems raise a connection or timeout error instead.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried create would start a second billable run. Opt in with `.retryWrites()` if your
call site can tolerate it.

## Webhooks

```java
WebhookEvent event = Webhook.parse(body, signature, secret);
```

`verify` returns the decoded payload, `parse` returns a typed event with
`items`, `files` and `statistics` reachable. A handler verifies once and routes
by event type. For a manifest delivery, `rows` downloads the NDJSON files and
checks the published SHA-256 before yielding anything.

## Sandbox

```
ZELF_BASE_URL=https://sandbox-api.hellozelf.com
ZELF_API_KEY=sk_zelf_sandbox_demo
```

Same response shapes and pagination as production, with canned data. It honours
`page` and `page_size` and ignores other filters.

The sandbox is not a stand-in for production behaviour. It validates nothing,
and it never reads a path parameter, so `INVALID_ID` and the other error cases
cannot be reached there. Test error handling and validation against production.

## Tests

```bash
mvn test
```

See the [repository README](../README.md) for the API surface, and
[docs/contributing.md](../docs/contributing.md) for how these are generated.
