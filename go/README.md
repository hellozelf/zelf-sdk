# zelf-go

Official client for the Zelf API. Part of
[hellozelf/zelf-sdk](https://github.com/hellozelf/zelf-sdk), which holds the
same client in eight languages.

## Install

```bash
go get github.com/hellozelf/zelf-sdk/go
```

```go
import zelf "github.com/hellozelf/zelf-sdk/go"

client, err := zelf.New(zelf.WithAPIKey("sk_zelf_..."))
```

## Client options

| Option | Default | What it does |
|---|---|---|
| `WithAPIKey` | `ZELF_API_KEY` | Brand API key, sent as `x-api-key` |
| `WithBaseURL` | `ZELF_BASE_URL`, else production | Point at the sandbox or another deployment |
| `WithTimeout` | 60s | Bounds each individual attempt, not the whole call |
| `WithMaxRetries` | 2 | How many times a retryable response is retried |
| `WithRetryWrites` | off | Allow non-idempotent requests to be retried |
| `WithHeader` | none | Added to every request |
| `WithHTTPClient` | built in | Supply your own HTTP client |

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

```go
page, err := client.Content.List(ctx, &zelf.ContentListParams{PageSize: zelf.Ptr(50)})

for _, item := range page.Results { }   // this page only

err = page.AutoPaging(ctx, visit)                     // every page
err = page.AutoPaging(ctx, visit, zelf.MaxPages(5))
err = page.AutoPaging(ctx, visit, zelf.MaxItems(100))

for item, err := range page.All(ctx, zelf.MaxItems(100)) { }
```

Optional request fields are pointers, so `zelf.Ptr` keeps call sites to one
line.

Some fields accept JSON null as a value of its own, separate from leaving the
field out. Those are typed `zelf.Nullable[T]`, which has its own two helpers.

```go
body := zelf.BrandCreateSubBrandRequest{
    BooleanQuery: zelf.Value("nike OR adidas"), // send the string
}

body.BooleanQuery = zelf.Null[string]()         // send JSON null
body.BooleanQuery = zelf.Nullable[string]{}     // leave the field out
```

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id`.

```go
_, err := client.Content.Details(ctx, "con_nope", nil)

var apiError *zelf.APIError
if errors.As(err, &apiError) {
    fmt.Println(apiError.Status, apiError.Code, apiError.LogID)
}
```

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server, service unavailable. Network
problems raise a connection or timeout error instead.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried create would start a second billable run. Opt in with `WithRetryWrites` if your
call site can tolerate it.

## Webhooks

```go
import "github.com/hellozelf/zelf-sdk/go/webhooks"

event, err := webhooks.Parse(body, signature, []string{secret}, webhooks.Options{})
```

`verify` returns the decoded payload, `parse` returns a typed event with
`items`, `files` and `statistics` reachable. A handler verifies once and routes
by event type. For a manifest delivery, `rows` downloads the NDJSON files and
checks the published SHA-256 before yielding anything.

## Sandbox

```bash
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
go test ./...
```

Types come from oapi-codegen under `internal/openapi` and are re-exported at
the package root, so `zelf.Content` is the name to use.

See the [repository README](../README.md) for the API surface, and
[docs/contributing.md](../docs/contributing.md) for how these are generated.
