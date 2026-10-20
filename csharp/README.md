# Zelf.Sdk (.NET)

Official client for the Zelf API. Part of
[hellozelf/zelf-sdk](https://github.com/hellozelf/zelf-sdk), which holds the
same client in eight languages.

## Install

```bash
dotnet add package Zelf.Sdk
```

```csharp
using Zelf;

using var client = new ZelfClient("sk_zelf_...");
```

Targets net8.0 and net10.0.

## Client options

| Option | Default | What it does |
|---|---|---|
| `ApiKey` | `ZELF_API_KEY` | Brand API key, sent as `x-api-key` |
| `BaseUrl` | `ZELF_BASE_URL`, else production | Point at the sandbox or another deployment |
| `Timeout` | 60s | Bounds each individual attempt, not the whole call |
| `MaxRetries` | 2 | How many times a retryable response is retried |
| `RetryWrites` | off | Allow non-idempotent requests to be retried |
| `DefaultHeaders` | none | Added to every request |
| `HttpClient` | built in | Supply your own HTTP client |

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

```csharp
var page = await client.Content.ListAsync(new ContentListParams { PageSize = 50 });

foreach (var item in page.Results) { }                 // this page only

await foreach (var item in page.AutoPagingAsync()) { } // every page
await foreach (var item in page.AutoPagingAsync(PageLimits.Pages(5))) { }
await foreach (var item in page.AutoPagingAsync(PageLimits.Items(100))) { }
```

Pass options with `new ZelfClient(new ZelfClientOptions { ... })`.

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id`.

```csharp
try
{
    await client.Content.DetailsAsync("con_nope");
}
catch (ZelfNotFoundException error)
{
    Console.WriteLine($"{error.Status} {error.Code} {error.LogId}");
}
```

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server, service unavailable. Network
problems raise a connection or timeout error instead.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried create would start a second billable run. Opt in with `RetryWrites` if your
call site can tolerate it.

## Webhooks

```csharp
var webhookEvent = Webhooks.Parse(body, headers, secret);
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
dotnet test
```

Enum-valued fields are wire strings with a constants class beside them, because
values like `-posted_at` are not valid C# identifiers.

See the [repository README](../README.md) for the API surface, and
[docs/contributing.md](../docs/contributing.md) for how these are generated.
