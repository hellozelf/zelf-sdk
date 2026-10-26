# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The clients carry their own version, set in `spec/sdk-version.txt` and shared
by all of them. A moved API surface costs a minor; a corrected description or a
fix in a client is a patch. Each entry names the OpenAPI document it was
generated from, which has a version of its own.

Entries below this line are written by `codegen/pipeline.py` from the
structural diff between releases.

## 1.3.3

### Changed
- `webhooks.create_subscription`: `interval_hours` changed type
- `webhooks.update_subscription`: `interval_hours` changed type
- `PatchedWebhookSubscriptionUpdateRequest.interval_hours` changed type
- `WebhookSubscriptionCreateRequest.interval_hours` changed type

### Removed
- `UsageDay.creator_vetting`

## 1.3.2

No change to the API surface. Corrected documentation, or a fix in the clients themselves.

## 1.3.1

No change to the API surface.

### Changed
- `last_keyword` says what it actually is: what the content was most
  recently collected under, which may be a hashtag, a creator handle, a
  search term or a brand identifier.
- A refused request carries the field and the limit in the exception
  message, not only in its details.

## 1.3.0

### Added
- `ContentFormEnum`: `PHOTO`

### Changed
- `content.list`: `content_form` changed type
- `content.statistics`: `content_form` changed type
- `ContentFilterInputRequest.content_form` changed type

### Removed
- `ContentFormEnum`: `IMAGE`

## 1.2.0

### Added
- `engage.comment_statistics` (GET /api/v1/engage/comment_statistics/)
- `CommentCategory`
- `CommentStatistics`

### Removed
- `analytics.posted_comments`
- `PostedCommentCategory`
- `PostedComments`

## 1.1.1

### Fixed
- `analytics.brand_comparison` and `analytics.follower_timeseries` return every
  row. Both were typed as a single object, so each client decoded `results[0]`
  and dropped the rest: a caller saw one brand and never a competitor. They now
  return a list, in every client.
- `brand_accounts.list`, `.add` and `.remove` return one `BrandAccountGroups`
  rather than a one-element list of it. The response is a single object holding
  `tracked`, `influencer` and `owned`, and the clients now say so.

### Changed
- Cardinality is read from the document rather than a table of operation names:
  a `page` parameter means a page, `results` with `maxItems: 1` means one row,
  anything else means a list. A new endpoint can no longer inherit the wrong
  shape by being absent from a list someone forgot to edit.

## 1.1.0

### Added
- `analytics.brand_comparison` (GET /api/v1/analytics/brand_comparison/)
- `analytics.follower_timeseries` (GET /api/v1/analytics/follower_timeseries/)
- `analytics.posted_comments` (GET /api/v1/analytics/posted_comments/)
- `AnalyticsBrand`
- `BrandComparison`
- `BrandFollowers`
- `BrandStatistics`
- `FollowerAccount`
- `FollowerPeriod`
- `FollowerTimeseries`
- `PostedCommentCategory`
- `PostedComments`
- `UsageDay`
- `UsageHistory`
- `Usage.history`
- `UsageScope.scope`
- `UsageWindow.window`

### Changed
- `Usage.scopes` changed type
- `UsageScope.windows` changed type

## 1.0.0

First release. 6 clients generated from the published OpenAPI document, covering all 48 operations.

Clients: Python, TypeScript, Go, Rust, Ruby, C#. A Java client is generated
and versioned with the rest, and is not published yet.

### Operations

- **ai_analysis**: `content_statistics`, `contents`, `create`, `list`, `results`
- **brand_accounts**: `add`, `list`, `remove`
- **brands**: `catalog`, `catalog_categories`, `list`, `update`
- **comments**: `list`
- **content**: `ai_summarize`, `details`, `discover`, `list`, `statistics`, `transcribe`
- **creator_sync**: `create`, `get`, `list`
- **creator_vetting**: `content_statistics`, `contents`, `create`, `list`, `results`
- **creators**: `list`
- **detection**: `create`, `get`, `list`
- **sub_brands**: `create`
- **usage**: `retrieve`
- **webhooks**: `create_secret`, `create_subscription`, `delete_secret`, `delete_subscription`, `get_delivery`, `get_secret`, `get_subscription`, `list_deliveries`, `list_events`, `list_secrets`, `list_subscriptions`, `rotate_subscription_secret`, `send_test`, `set_default_secret`, `update_subscription`

### Webhook events

- `ai_analysis.completed`
- `content.snapshot`
- `creator.snapshot`
- `creator_vetting.completed`

### Types

- 63 models and 13 enums, generated from the document
- 8 error codes, each with its own exception type

### Client behaviour

- The same resources and method names in every language
- Cursor-free pagination with three bounds: everything, N pages, or N items
- Typed errors carrying the API's error code and `log_id`
- Retries honouring `Retry-After`; writes are never retried, because the API publishes no idempotency key
- Webhook verification, typed events, a routing handler, and manifest downloads checked against the published SHA-256
- `ZELF_API_KEY` and `ZELF_BASE_URL` are read from the environment

