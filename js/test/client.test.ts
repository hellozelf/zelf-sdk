import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHmac } from 'node:crypto'

import {
  ZelfAPIClient,
  AuthenticationError,
  NotFoundError,
  RateLimitError,
  Page,
  webhooks,
} from '../dist/index.js'
import type { Content } from '../dist/index.js'

const BASE = 'https://api.hellozelf.com'
const KEY = 'sk_test_not_a_real_key'

const CONTENT = {
  id: 'con_1',
  platform_post_id: '73765',
  platform: 'instagram',
  posted_at: '2026-05-12T16:00:00Z',
  view_count: 184230,
} as unknown as Content

function envelope(results: unknown[], page = 1, next: number | null = null) {
  return {
    log_id: 'log_1',
    timestamp: '2026-01-01T00:00:00Z',
    applied_filters: { page, page_size: 30 },
    results,
    item_count: results.length,
    page,
    next,
    previous: page > 1 ? page - 1 : null,
  }
}

function stub(responses: Array<{ status?: number; body?: unknown; headers?: Record<string, string> }>) {
  const calls: Request[] = []
  let index = 0
  const fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(new Request(typeof input === 'string' ? input : String(input), init))
    const next = responses[Math.min(index, responses.length - 1)]!
    index += 1
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), {
      status: next.status ?? 200,
      headers: { 'content-type': 'application/json', ...next.headers },
    })
  }
  return { calls, fetch: fetch as unknown as typeof globalThis.fetch }
}

test('list returns a typed page', async () => {
  const { calls, fetch } = stub([{ body: envelope([CONTENT]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const page = await client.content.list({ search: 'running shoes' })

  assert.ok(page instanceof Page)
  assert.equal(page.results[0]!.id, 'con_1')
  assert.equal(page.meta.itemCount, 1)
  assert.equal(page.hasNext, false)
  assert.equal(new URL(calls[0]!.url).searchParams.get('search'), 'running shoes')
})

test('camelCase arguments map onto the snake_case wire names', async () => {
  const { calls, fetch } = stub([{ body: envelope([]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await client.content.list({ brandId: 'brd_1', postedWithinDays: 30, isOwned: true })
  const params = new URL(calls[0]!.url).searchParams

  assert.equal(params.get('brand_id'), 'brd_1')
  assert.equal(params.get('posted_within_days'), '30')
  assert.equal(params.get('is_owned'), 'true')
})

test('array query parameters repeat the key and dates become ISO strings', async () => {
  const { calls, fetch } = stub([{ body: envelope([]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await client.content.list({
    platform: ['instagram', 'tiktok'],
    postedAfter: new Date(Date.UTC(2026, 0, 1)),
  })
  const params = new URL(calls[0]!.url).searchParams

  assert.deepEqual(params.getAll('platform'), ['instagram', 'tiktok'])
  assert.equal(params.get('posted_after'), '2026-01-01T00:00:00.000Z')
  assert.equal(params.has('brand_id'), false)
})

test('autoPaging walks every page', async () => {
  const { calls, fetch } = stub([
    { body: envelope([{ ...CONTENT, id: 'con_1' }], 1, 2) },
    { body: envelope([{ ...CONTENT, id: 'con_2' }], 2, 3) },
    { body: envelope([{ ...CONTENT, id: 'con_3' }], 3) },
  ])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const seen: string[] = []
  for await (const item of (await client.content.list({ search: 'x' })).autoPaging()) {
    seen.push(item.id)
  }

  assert.deepEqual(seen, ['con_1', 'con_2', 'con_3'])
  assert.deepEqual(
    calls.map((call) => new URL(call.url).searchParams.get('page')),
    [null, '2', '3'],
  )
})

test('a single read unwraps the envelope', async () => {
  const { fetch } = stub([{ body: envelope([CONTENT]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  assert.equal((await client.content.details('con_1')).id, 'con_1')
})

test('a single read that matches nothing raises a 404', async () => {
  const { fetch } = stub([{ body: envelope([]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await assert.rejects(client.content.details('con_missing'), (error: unknown) => {
    assert.ok(error instanceof NotFoundError)
    assert.equal(error.status, 404)
    assert.equal(error.code, 'NOT_FOUND')
    assert.match(error.message, /No Content matched/)
    return true
  })
})

test('the api key goes in a header, never the url', async () => {
  const { calls, fetch } = stub([{ body: envelope([{ plan: 'pro' }]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await client.usage.retrieve()

  assert.equal(calls[0]!.headers.get('x-api-key'), KEY)
  assert.ok(!calls[0]!.url.includes(KEY))
  assert.ok(calls[0]!.headers.get('user-agent')!.startsWith('zelf-node/'))
})

test('the api key never leaks through JSON.stringify', () => {
  const client = new ZelfAPIClient({ apiKey: KEY, fetch: stub([]).fetch })

  assert.ok(!JSON.stringify(client).includes(KEY))
  assert.match(JSON.stringify(client), /"apiKey":"\*\*\*"/)
})

test('a missing api key fails before any request', () => {
  const previous = process.env.ZELF_API_KEY
  delete process.env.ZELF_API_KEY
  try {
    assert.throws(() => new ZelfAPIClient(), /apiKey is required/)
  } finally {
    if (previous !== undefined) process.env.ZELF_API_KEY = previous
  }
})

test('path parameters are url encoded', async () => {
  const { calls, fetch } = stub([{ body: envelope([CONTENT]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await client.content.details('con/../../admin')

  assert.ok(calls[0]!.url.includes('/api/v1/content/con%2F..%2F..%2Fadmin/'))
})

test('errors map to typed classes carrying the api error code', async () => {
  const { fetch } = stub([
    {
      status: 401,
      body: { log_id: 'log_1', error: { code: 'INVALID_API_KEY', message: 'Nope.', details: {} } },
    },
  ])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch, maxRetries: 0 })

  await assert.rejects(client.content.list({ search: 'x' }), (error: unknown) => {
    assert.ok(error instanceof AuthenticationError)
    assert.equal(error.status, 401)
    assert.equal(error.code, 'INVALID_API_KEY')
    assert.equal(error.logId, 'log_1')
    return true
  })
})

test('a rate limited read is retried', async () => {
  const { calls, fetch } = stub([
    { status: 429, body: { error: { code: 'RATE_LIMIT_EXCEEDED' } }, headers: { 'retry-after': '0' } },
    { body: envelope([CONTENT]) },
  ])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch, maxRetries: 2 })

  const page = await client.content.list({ search: 'x' })

  assert.equal(page.results.length, 1)
  assert.equal(calls.length, 2)
})

test('a write is not retried by default', async () => {
  const { calls, fetch } = stub([{ status: 503, body: { error: { code: 'SERVICE_UNAVAILABLE' } } }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch, maxRetries: 3 })

  await assert.rejects(client.creatorSync.create({ profileUrl: 'https://tiktok.com/@zelf' }))

  assert.equal(calls.length, 1)
})

test('a client error is never retried', async () => {
  const { calls, fetch } = stub([{ status: 400, body: { error: { code: 'VALIDATION_ERROR' } } }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch, maxRetries: 3 })

  await assert.rejects(client.content.list({ search: 'x' }))

  assert.equal(calls.length, 1)
})

test('request bodies are built from camelCase arguments', async () => {
  const { calls, fetch } = stub([{ status: 201, body: envelope([{ id: 'ana_1' }]) }])
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  await client.aiAnalysis.create({
    name: 'Launch sentiment',
    topic: 'sentiment',
    contentFilters: { search: 'zelf' },
    analysisScope: ['CONTENT'],
  })

  assert.deepEqual(JSON.parse(await calls[0]!.text()), {
    name: 'Launch sentiment',
    topic: 'sentiment',
    content_filters: { search: 'zelf' },
    analysis_scope: ['CONTENT'],
  })
})

function sign(payload: Uint8Array, secret: string, timestamp: number) {
  const digest = createHmac('sha256', secret)
    .update(Buffer.concat([Buffer.from(`${timestamp}.`), Buffer.from(payload)]))
    .digest('hex')
  return { 'webhook-signature': `t=${timestamp},v1=${digest}`, 'webhook-timestamp': String(timestamp) }
}

const BODY = new TextEncoder().encode(JSON.stringify({ id: 'whd_1', type: 'content.snapshot' }))
const SECRET = 'whsec_abcdef'

test('a genuine webhook verifies', async () => {
  const now = Math.floor(Date.now() / 1000)
  const payload = await webhooks.verify(BODY, sign(BODY, SECRET, now), SECRET, { now })

  assert.equal(payload.id, 'whd_1')
})

test('a forged webhook signature is rejected', async () => {
  const now = Math.floor(Date.now() / 1000)
  await assert.rejects(
    webhooks.verify(BODY, sign(BODY, 'whsec_wrong', now), SECRET, { now }),
    /No signature matched/,
  )
})

test('a tampered webhook body is rejected', async () => {
  const now = Math.floor(Date.now() / 1000)
  const tampered = new TextEncoder().encode(JSON.stringify({ id: 'whd_2' }))
  await assert.rejects(
    webhooks.verify(tampered, sign(BODY, SECRET, now), SECRET, { now }),
    /No signature matched/,
  )
})

test('an old webhook is rejected as a replay', async () => {
  const stale = Math.floor(Date.now() / 1000) - 4000
  await assert.rejects(webhooks.verify(BODY, sign(BODY, SECRET, stale), SECRET), /replay/)
})

test('either secret verifies during a rotation', async () => {
  const now = Math.floor(Date.now() / 1000)
  const headers = sign(BODY, 'whsec_new', now)

  assert.ok(await webhooks.verify(BODY, headers, ['whsec_old', 'whsec_new'], { now }))
})

test('passing a decoded string is refused', async () => {
  const now = Math.floor(Date.now() / 1000)
  await assert.rejects(
    webhooks.verify('{}' as unknown as Uint8Array, sign(BODY, SECRET, now), SECRET, { now }),
    /raw request bytes/,
  )
})

function pageResponses(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    body: envelope([{ ...CONTENT, id: `con_${index + 1}` }], index + 1, index + 1 < count ? index + 2 : null),
  }))
}

test('maxPages stops the walk early', async () => {
  const { calls, fetch } = stub(pageResponses(5))
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const seen: string[] = []
  for await (const item of (await client.content.list({ search: 'x' })).autoPaging({ maxPages: 3 })) {
    seen.push(item.id)
  }

  assert.deepEqual(seen, ['con_1', 'con_2', 'con_3'])
  assert.equal(calls.length, 3)
})

test('maxPages of one makes no further request', async () => {
  const { calls, fetch } = stub(pageResponses(5))
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const seen: string[] = []
  for await (const item of (await client.content.list({ search: 'x' })).autoPaging({ maxPages: 1 })) {
    seen.push(item.id)
  }

  assert.deepEqual(seen, ['con_1'])
  assert.equal(calls.length, 1)
})

test('maxItems stops before fetching a page it does not need', async () => {
  const { calls, fetch } = stub(pageResponses(5))
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const seen: string[] = []
  for await (const item of (await client.content.list({ search: 'x' })).autoPaging({ maxItems: 2 })) {
    seen.push(item.id)
  }

  assert.deepEqual(seen, ['con_1', 'con_2'])
  assert.equal(calls.length, 2)
})

test('pages honours maxPages', async () => {
  const { calls, fetch } = stub(pageResponses(5))
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })

  const seen: number[] = []
  for await (const page of (await client.content.list({ search: 'x' })).pages(2)) {
    seen.push(page.meta.page)
  }

  assert.deepEqual(seen, [1, 2])
  assert.equal(calls.length, 2)
})

test('a limit below one is rejected', async () => {
  const { fetch } = stub(pageResponses(2))
  const client = new ZelfAPIClient({ apiKey: KEY, fetch })
  const page = await client.content.list({ search: 'x' })

  await assert.rejects(async () => {
    for await (const _ of page.autoPaging({ maxPages: 0 })) { /* unreachable */ }
  }, RangeError)
  await assert.rejects(async () => {
    for await (const _ of page.autoPaging({ maxItems: 0 })) { /* unreachable */ }
  }, RangeError)
})
