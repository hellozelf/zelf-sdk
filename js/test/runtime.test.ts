import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHmac } from 'node:crypto'
import { readFileSync } from 'node:fs'

import {
  ZelfAPIClient,
  ZelfAPIError,
  ZelfTimeoutError,
  ZelfConnectionError,
  NotFoundError,
  Page,
  webhooks,
} from '../dist/index.js'

const FIXTURES = JSON.parse(
  readFileSync(new URL('../../fixtures.json', import.meta.url), 'utf8'),
) as { envelopes: Record<string, any> }

const KEY = 'sk_zelf_' + '0'.repeat(64)
const BRANDS = FIXTURES.envelopes.brands_list
const SECRET = 'whsec_abcdef0123456789'

function respond(body: unknown, status = 200, contentType = 'application/json') {
  return async () =>
    new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status,
      headers: { 'content-type': contentType },
    })
}

function failing(cause: unknown) {
  return async () => {
    throw cause
  }
}

function client(fetch: unknown) {
  return new ZelfAPIClient({ apiKey: KEY, maxRetries: 0, fetch: fetch as typeof globalThis.fetch })
}

test('a page is iterable', async () => {
  const page = await client(respond(BRANDS)).brands.list()
  assert.ok(page instanceof Page)
  assert.deepEqual([...page], page.results)
})

test('a results field that is not an array is rejected', async () => {
  const body = { ...BRANDS, results: { id: 'brd_1' } }
  await assert.rejects(() => client(respond(body)).brands.list(), TypeError)
})

test('a body that is not JSON becomes a typed error', async () => {
  await assert.rejects(
    () => client(respond('<html>', 200, 'text/html')).usage.retrieve(),
    (error: unknown) => error instanceof ZelfAPIError && /not valid JSON/.test(String(error)),
  )
})

test('an envelope that is not an object becomes a typed error', async () => {
  await assert.rejects(
    () => client(respond([1, 2, 3])).usage.retrieve(),
    (error: unknown) => error instanceof ZelfAPIError && /not an object/.test(String(error)),
  )
})

test('an error status with an unreadable body still raises', async () => {
  await assert.rejects(
    () => client(respond('nope', 500, 'text/plain')).usage.retrieve(),
    ZelfAPIError,
  )
})

test('an error envelope raises the typed subclass', async () => {
  const body = {
    log_id: 'log_1',
    timestamp: '2026-01-01T00:00:00Z',
    error: { code: 'NOT_FOUND', message: 'Resource not found.', details: {} },
  }
  await assert.rejects(() => client(respond(body, 404)).usage.retrieve(), NotFoundError)
})

test('a timeout becomes a typed timeout error', async () => {
  const cause = new Error('slow')
  cause.name = 'TimeoutError'
  await assert.rejects(() => client(failing(cause)).usage.retrieve(), ZelfTimeoutError)
})

test('an abort becomes a typed connection error', async () => {
  const cause = new Error('stopped')
  cause.name = 'AbortError'
  await assert.rejects(() => client(failing(cause)).usage.retrieve(), ZelfConnectionError)
})

test('any other transport failure becomes a connection error', async () => {
  await assert.rejects(() => client(failing(new Error('socket closed'))).usage.retrieve(), ZelfConnectionError)
})

test('a non-Error rejection still becomes a connection error', async () => {
  await assert.rejects(() => client(failing('dropped')).usage.retrieve(), ZelfConnectionError)
})

test('an empty path parameter is refused before the request', async () => {
  await assert.rejects(
    () => client(respond(BRANDS)).content.details(''),
    /required and must not be empty/,
  )
})


function sign(body: Uint8Array, secret: string, timestamp: number) {
  const payload = body
  const digest = createHmac('sha256', secret)
    .update(`${timestamp}.`)
    .update(payload)
    .digest('hex')
  return {
    'Webhook-Id': 'whd_1',
    'Webhook-Timestamp': String(timestamp),
    'Webhook-Signature': `t=${timestamp},v1=${digest}`,
  }
}

const PUSH = {
  id: 'whd_1',
  type: 'content.snapshot',
  subscription_id: 'whs_1',
  delivered_at: 1718000000,
  livemode: true,
  resource: 'content',
  resource_filters: {},
  delivery_mode: 'inline',
  data: { items: [{ id: 'con_1' }], item_count: 1, statistics: { post_count: 1 } },
}

test('headers can be a Headers instance', async () => {
  const body = new TextEncoder().encode(JSON.stringify(PUSH))
  const now = Math.floor(Date.now() / 1000)
  const headers = new Headers(sign(body, SECRET, now))
  const payload = await webhooks.verify(body, headers, SECRET)
  assert.equal(payload.id, 'whd_1')
})

test('a missing signature header is refused', async () => {
  await assert.rejects(
    () => webhooks.verify(new TextEncoder().encode(JSON.stringify(PUSH)), {}, SECRET),
    webhooks.WebhookVerificationError,
  )
})

test('a signature with a non-integer timestamp is refused', async () => {
  const headers = { 'Webhook-Signature': 't=soon,v1=abc' }
  await assert.rejects(() => webhooks.verify(new TextEncoder().encode(JSON.stringify(PUSH)), headers, SECRET), /not an integer/)
})

test('a signature missing a component is refused', async () => {
  const headers = { 'Webhook-Signature': 'v1=abc' }
  await assert.rejects(() => webhooks.verify(new TextEncoder().encode(JSON.stringify(PUSH)), headers, SECRET), /missing a/)
})

test('a body that is not JSON is refused', async () => {
  const body = new TextEncoder().encode('not json')
  const now = Math.floor(Date.now() / 1000)
  await assert.rejects(
    () => webhooks.verify(body, sign(body, SECRET, now), SECRET),
    /not valid JSON/,
  )
})

test('a body that is a JSON array is refused', async () => {
  const body = new TextEncoder().encode('[1,2,3]')
  const now = Math.floor(Date.now() / 1000)
  await assert.rejects(
    () => webhooks.verify(body, sign(body, SECRET, now), SECRET),
    /not a JSON object/,
  )
})

test('an event exposes its type, mode, statistics and count', async () => {
  const body = new TextEncoder().encode(JSON.stringify(PUSH))
  const now = Math.floor(Date.now() / 1000)
  const event = await webhooks.parse(body, sign(body, SECRET, now), SECRET)

  assert.equal(event.eventType, 'content.snapshot')
  assert.equal(event.deliveryMode, 'inline')
  assert.deepEqual(event.statistics, { post_count: 1 })
  assert.equal(event.itemCount, 1)
})

test('an unknown event type reads back as null', async () => {
  const body = new TextEncoder().encode(JSON.stringify({ ...PUSH, type: 'content.from_the_future' }))
  const now = Math.floor(Date.now() / 1000)
  const event = await webhooks.parse(body, sign(body, SECRET, now), SECRET)
  assert.equal(event.eventType, null)
})

test('a retry without a Retry-After header backs off on its own', async () => {
  let calls = 0
  const fetch = async () => {
    calls += 1
    return new Response(JSON.stringify({ error: { code: 'INTERNAL_ERROR', message: 'boom' } }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    })
  }
  const client = new ZelfAPIClient({
    apiKey: KEY,
    maxRetries: 1,
    fetch: fetch as typeof globalThis.fetch,
  })

  await assert.rejects(() => client.usage.retrieve(), ZelfAPIError)
  assert.equal(calls, 2)
})
