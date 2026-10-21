# zelf-sdk (Ruby)

Official client for the Zelf API. Part of
[hellozelf/zelf-sdk](https://github.com/hellozelf/zelf-sdk).

## Install

```bash
gem install zelf-sdk
```

The gem publishes as `zelf-sdk` and requires as `zelf`.

```ruby
require 'zelf'

client = Zelf::Client.new(api_key: 'sk_zelf_...')
```

## Client options

| Option | Default | What it does |
|---|---|---|
| `api_key:` | `ZELF_API_KEY` | Brand API key, sent as `x-api-key` |
| `base_url:` | `ZELF_BASE_URL`, else production | Point at the sandbox or another deployment |
| `timeout:` | 60s | Bounds each individual attempt, not the whole call |
| `max_retries:` | 2 | How many times a retryable response is retried |
| `retry_writes:` | off | Allow non-idempotent requests to be retried |
| `headers:` | none | Added to every request |
| n/a | built in | Supply your own HTTP client |

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

```ruby
page = client.content.list(page_size: 50)

page.results.each { |item| }                  # this page only
page.auto_paging { |item| }                   # every page
page.auto_paging(max_pages: 5) { |item| }
page.auto_paging(max_items: 100) { |item| }
```

## Errors

Every failure is a typed error carrying the status, the API's error code and
the `log_id`.

```ruby
begin
  client.content.details('con_nope')
rescue Zelf::NotFoundError => error
  puts error.status, error.code, error.log_id
end
```

The type follows the status: bad request, authentication, permission denied,
not found, conflict, rate limit, internal server, service unavailable. Network
problems raise a connection or timeout error instead.

## Retries

A failed GET is retried twice by default, honouring `Retry-After` and otherwise
backing off exponentially with jitter, capped at 8 seconds.

**Writes are never retried.** The API publishes no `Idempotency-Key`, so a
retried create would start a second billable run. Opt in with `retry_writes:` if your
call site can tolerate it.

## Webhooks

```ruby
event = Zelf::Webhooks.parse(body, headers, secret)
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
for f in test/*_test.rb; do ruby -Itest "$f"; done
```

Supported on Ruby 3.1 and newer.

See the [repository README](../README.md) for the API surface, and
[docs/contributing.md](../docs/contributing.md) for how these are generated.
