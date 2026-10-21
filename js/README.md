# zelf-sdk (TypeScript)

Official client for the Zelf API. Part of
[hellozelf/zelf-sdk](https://github.com/hellozelf/zelf-sdk).

## Install

```bash
npm install zelf-sdk
```

```ts
import { ZelfAPIClient } from 'zelf-sdk'

const client = new ZelfAPIClient({ apiKey: 'sk_zelf_...' })
```

## Client options

| Option | Default | What it does |
|---|---|---|
| `apiKey` | `ZELF_API_KEY` | Brand API key, sent as `x-api-key` |
| `baseUrl` | `ZELF_BASE_URL`, else production | Point at the sandbox or another deployment |
| `timeoutMs` | 60s | Bounds each individual attempt, not the whole call |
| `maxRetries` | 2 | How many times a retryable response is retried |
| `retryWrites` | off | Allow non-idempotent requests to be retried |
| `defaultHeaders` | none | Added to every request |
| `fetch` | built in | Supply your own HTTP client |

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

```ts
const page = await client.content.list({ pageSize: 50 })

for (const item of page.results) { }            // this page only
for await (const item of page.autoPaging()) { } // every page
for await (const item of page.autoPaging({ maxPages: 5 })) { }
for await (const item of page.autoPaging({ maxItems: 100 })) { }
```

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id`.

```ts
try {
  await client.content.details('con_nope')
} catch (error) {
  if (error instanceof NotFoundError) {
    console.log(error.status, error.code, error.logId)
  }
}
```

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server, service unavailable. Network
problems raise a connection or timeout error instead.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried create would start a second billable run. Opt in with `retryWrites` if your
call site can tolerate it.

## Webhooks

```ts
import { webhooks } from 'zelf-sdk'

const event = await webhooks.parse(body, headers, secret)
if (event.eventType === webhooks.EventType.ContentSnapshot) { }
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
npm test
```

See the [repository README](../README.md) for the API surface, and
[docs/contributing.md](../docs/contributing.md) for how these are generated.
