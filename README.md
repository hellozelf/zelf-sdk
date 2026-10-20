# Zelf SDKs

Official clients for the Zelf API in Python, TypeScript and Go. One spec,
three clients, the same resources and method names in each.

```bash
pip install zelf-sdk
```

```python
from zelf import ZelfAPIClient

client = ZelfAPIClient(api_key="sk_zelf_...")

page = client.content.list(brand_id="brd_6u5...", posted_within_days=30)
for item in page:
    print(item.view_count, item.caption)
```

Examples on this page are Python. Each one is followed by the same call in
TypeScript and Go, collapsed. Per-language detail lives in that language's own
README: [Python](python/README.md), [TypeScript](js/README.md),
[Go](go/README.md).

## Install

| Language | Install | Import |
|---|---|---|
| Python | `pip install zelf-sdk` | `from zelf import ZelfAPIClient` |
| TypeScript | `npm install zelf-sdk` | `import { ZelfAPIClient } from 'zelf-sdk'` |
| Go | `go get github.com/hellozelf/zelf-sdk/go` | `import zelf "github.com/hellozelf/zelf-sdk/go"` |

The package is `zelf-sdk` because `zelf` was taken on npm and crates.io. The
import stays `zelf` everywhere the two can differ.

## Authentication

Pass the key, or set `ZELF_API_KEY` and pass nothing. It is sent as the
`x-api-key` header and never as a query parameter. Point a client at another
deployment with the base URL option, or set `ZELF_BASE_URL`.

**Python**

```python
client = ZelfAPIClient(api_key="sk_zelf_...")
client = ZelfAPIClient()                       # reads ZELF_API_KEY
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
const client = new ZelfAPIClient({ apiKey: 'sk_zelf_...' })
```

**Go**

```go
client, err := zelf.New(zelf.WithAPIKey("sk_zelf_..."))
```

</details>

## Calling the API

Operation ids read as `resource.method`, so `content.list` is
`client.content.list()` in every language.

**Python**

```python
page = client.content.list(search="running shoes", brand_id="brd_1")
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
const page = await client.content.list({ search: 'running shoes' })
```

**Go**

```go
page, err := client.Content.List(ctx, &zelf.ContentListParams{Search: zelf.Ptr("running shoes")})
```

</details>

Python also ships an async client with the same surface:

```python
from zelf import ZelfAPIClientAsync

async with ZelfAPIClientAsync() as client:
    page = await client.content.list(brand_id="brd_1")
```

## Pagination

A list call returns one page. Walking the rest takes one of three bounds:
everything, at most N pages, or at most N items. The item bound never fetches a
page it does not need.

**Python**

```python
for item in page.auto_paging(max_pages=5):
    print(item.id)
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
for await (const item of page.autoPaging({ maxPages: 5 })) { }
```

**Go**

```go
err = page.AutoPaging(ctx, visit, zelf.MaxPages(5))
```

</details>

The envelope is on the page itself: `page.item_count`, `page.page`,
`page.applied_filters`, `page.log_id`.

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id` to quote in a support request.

**Python**

```python
try:
    client.content.details("con_nope")
except zelf.NotFoundError as error:
    print(error.status_code, error.code, error.log_id)
```

```text
404 NOT_FOUND 0ca57078-d810-4038-a1d7-02953ac7ce60
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
try {
  await client.content.details('con_nope')
} catch (error) {
  if (error instanceof NotFoundError) console.log(error.status, error.code)
}
```

**Go**

```go
_, err := client.Content.Details(ctx, "con_nope", nil)
var apiError *zelf.APIError
if errors.As(err, &apiError) {
    fmt.Println(apiError.Status, apiError.Code, apiError.LogID)
}
```

</details>

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server and service unavailable.
Network problems raise a connection or timeout error instead, so a retry
decision never has to parse a message.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried `detection.create` would start a second billable run. Opt in per client
if your call site can tolerate it:

**Python**

```python
client = ZelfAPIClient(max_retries=5, retry_writes=True)
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
new ZelfAPIClient({ maxRetries: 5, retryWrites: true })
```

**Go**

```go
zelf.New(zelf.WithMaxRetries(5), zelf.WithRetryWrites(true))
```

</details>

## Webhooks

`verify` checks the signature and returns the decoded payload. `parse` returns
a typed event instead.

**Python**

```python
from zelf import webhooks

event = webhooks.parse(request.body, request.headers, secret)
if event.event_type is webhooks.EventType.CONTENT_SNAPSHOT:
    for row in event.items:
        print(row["id"])
```

Verification uses each language's constant-time comparison, enforces a 300
second timestamp window against replays, and accepts a list of secrets so a
rotation does not drop deliveries.

A `Handler` verifies once and routes to the listener for the event type:

**Python**

```python
handler = (
    webhooks.WebhookHandler(secret)
    .on(webhooks.EventType.CONTENT_SNAPSHOT, on_snapshot)
    .on_any(on_everything_else)
)
event = handler.handle(request.body, request.headers)
```

<details>
<summary>The same in TypeScript and Go</summary>

**TypeScript**

```ts
const handler = new webhooks.WebhookHandler(secret)
  .on(webhooks.EventType.ContentSnapshot, onSnapshot)
  .onAny(onEverythingElse)
```

**Go**

```go
handler := webhooks.NewHandler([]string{secret}, webhooks.Options{}).
    On(onSnapshot, webhooks.EventContentSnapshot).
    OnAny(onEverythingElse)
```

</details>

For a manifest delivery, `rows` downloads the NDJSON files and verifies the
published SHA-256 over each body before yielding anything.

## Sandbox

A stub of the API, with canned data, for testing against. The key is public.

```bash
curl -H "x-api-key: sk_zelf_sandbox_demo" \
  "https://sandbox-api.hellozelf.com/api/v1/content/?page_size=3"
```

```python
client = ZelfAPIClient(
    api_key="sk_zelf_sandbox_demo",
    base_url="https://sandbox-api.hellozelf.com",
)
```

Every client reads `ZELF_BASE_URL`, so pointing a test suite at it needs no
code change:

```bash
export ZELF_BASE_URL=https://sandbox-api.hellozelf.com
export ZELF_API_KEY=sk_zelf_sandbox_demo
```

It returns the same response shapes and pagination as production, over canned
data. Send `x-sandbox-force-error: RATE_LIMIT_EXCEEDED` to drive a retry path.

The sandbox is not a stand-in for production behaviour. It validates nothing,
and it never reads a path parameter, so `INVALID_ID` and the other error cases
cannot be reached there. Test error handling and validation against production.

## Contributing

These clients are generated. See [docs/contributing.md](docs/contributing.md)
before changing anything under a language directory.

## License

Apache-2.0. See [LICENSE](LICENSE).
