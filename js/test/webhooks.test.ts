import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash, createHmac } from 'node:crypto'

import { webhooks } from '../dist/index.js'

const SECRET = 'whsec_abcdef0123456789'

function snapshot(
  overrides: { files?: unknown[]; items?: unknown[]; type?: string } = {},
): Record<string, unknown> {
  const data: Record<string, unknown> = { item_count: overrides.items?.length ?? 1 }
  if (overrides.files) data.files = overrides.files
  if (overrides.items) data.items = overrides.items
  return {
    id: 'whd_8f2c1d4e9a',
    type: overrides.type ?? 'content.snapshot',
    subscription_id: 'whs_5Kq9Wd2pBxLm',
    delivered_at: 1718000000,
    livemode: true,
    resource: 'content',
    resource_filters: {},
    delivery_mode: overrides.files ? 'manifest' : 'inline',
    data,
  }
}

function delivery(body: Record<string, unknown>, secret = SECRET) {
  const payload = new TextEncoder().encode(JSON.stringify(body))
  const now = Math.floor(Date.now() / 1000)
  const digest = createHmac('sha256', secret)
    .update(Buffer.concat([Buffer.from(`${now}.`), Buffer.from(payload)]))
    .digest('hex')
  return { payload, headers: { 'webhook-signature': `t=${now},v1=${digest}` }, now }
}

test('parse returns a typed event', async () => {
  const { payload, headers, now } = delivery(snapshot({ items: [{ id: 'con_1' }] }))

  const event = await webhooks.parse(payload, headers, SECRET, { now })

  assert.ok(event instanceof webhooks.WebhookEvent)
  assert.equal(event.type, webhooks.EventType.ContentSnapshot)
  assert.equal(event.id, 'whd_8f2c1d4e9a')
  assert.equal(event.subscriptionId, 'whs_5Kq9Wd2pBxLm')
  assert.equal(event.livemode, true)
  assert.equal(event.deliveredAt.getUTCFullYear(), 2024)
  assert.deepEqual(event.items, [{ id: 'con_1' }])
  assert.deepEqual(event.files, [])
})

test('the raw payload survives a field the sdk does not know', async () => {
  const { payload, headers, now } = delivery({ ...snapshot({ items: [] }), future: 42 })

  const event = await webhooks.parse(payload, headers, SECRET, { now })

  assert.equal(event.raw.future, 42)
})

test('the EventType object covers every declared event', () => {
  assert.deepEqual(Object.values(webhooks.EventType).sort(), [
    'ai_analysis.completed',
    'content.snapshot',
    'creator.snapshot',
    'creator_vetting.completed',
  ])
  assert.equal(webhooks.isEventType('content.snapshot'), true)
  assert.equal(webhooks.isEventType('content.exploded'), false)
})

test('the handler routes to the listener for the type', async () => {
  const seen: string[] = []
  const handler = new webhooks.WebhookHandler(SECRET)
    .on(webhooks.EventType.ContentSnapshot, (event) => {
      seen.push(`content:${event.id}`)
      return 'handled'
    })
    .on(webhooks.EventType.CreatorSnapshot, () => seen.push('creator'))

  const { payload, headers, now } = delivery(snapshot({ items: [] }))
  const results = await handler.handle(payload, headers, { now })

  assert.deepEqual(seen, ['content:whd_8f2c1d4e9a'])
  assert.deepEqual(results, ['handled'])
})

test('one listener can take several types', async () => {
  const seen: string[] = []
  const handler = new webhooks.WebhookHandler(SECRET).on(
    [webhooks.EventType.ContentSnapshot, webhooks.EventType.CreatorSnapshot],
    (event) => seen.push(event.type),
  )

  const { payload, headers, now } = delivery(snapshot({ items: [], type: 'creator.snapshot' }))
  await handler.handle(payload, headers, { now })

  assert.deepEqual(seen, ['creator.snapshot'])
})

test('an unmatched event falls back, or is a no-op without one', async () => {
  const seen: string[] = []
  const withFallback = new webhooks.WebhookHandler(SECRET).onAny((event) => seen.push(event.type))
  const bare = new webhooks.WebhookHandler(SECRET)

  const { payload, headers, now } = delivery(snapshot({ items: [], type: 'ai_analysis.completed' }))
  await withFallback.handle(payload, headers, { now })

  assert.deepEqual(seen, ['ai_analysis.completed'])
  assert.deepEqual(await bare.handle(payload, headers, { now }), [])
})

test('registering an unknown event type fails loudly', () => {
  const handler = new webhooks.WebhookHandler(SECRET)

  assert.throws(() => handler.on('content.exploded', () => {}), RangeError)
  assert.throws(() => handler.on([], () => {}), RangeError)
})

test('no listener runs when the signature is bad', async () => {
  const seen: string[] = []
  const handler = new webhooks.WebhookHandler(SECRET).onAny((event) => seen.push(event.type))

  const { payload, headers, now } = delivery(snapshot({ items: [] }), 'whsec_wrong')

  await assert.rejects(handler.handle(payload, headers, { now }), /No signature matched/)
  assert.deepEqual(seen, [])
})

const NDJSON = '{"id":"con_1"}\n{"id":"con_2"}\n'
const DIGEST = createHash('sha256').update(NDJSON).digest('hex')
const DOWNLOAD = 'https://storage.googleapis.com/zelf/whd_1.ndjson?sig=x'

function manifest(sha256 = DIGEST) {
  return snapshot({
    files: [
      {
        format: 'ndjson',
        expires_at: 1718000000,
        sha256,
        size_bytes: NDJSON.length,
        item_count: 2,
        download_url: DOWNLOAD,
      },
    ],
  })
}

function downloadStub(body: string, status = 200) {
  return (async () => new Response(body, { status })) as unknown as typeof globalThis.fetch
}

test('rows downloads the manifest and yields each line', async () => {
  const { payload, headers, now } = delivery(manifest())
  const event = await webhooks.parse(payload, headers, SECRET, { now })

  const rows = []
  for await (const row of event.rows({ fetch: downloadStub(NDJSON) })) rows.push(row)

  assert.deepEqual(rows, [{ id: 'con_1' }, { id: 'con_2' }])
})

test('rows rejects a download whose checksum does not match', async () => {
  const { payload, headers, now } = delivery(manifest())
  const event = await webhooks.parse(payload, headers, SECRET, { now })

  await assert.rejects(async () => {
    for await (const _ of event.rows({ fetch: downloadStub('{"id":"tampered"}\n') })) { /* unreachable */ }
  }, /does not match/)
})

test('rows rejects a manifest that published no digest', async () => {
  const { payload, headers, now } = delivery(manifest(''))
  const event = await webhooks.parse(payload, headers, SECRET, { now })

  await assert.rejects(async () => {
    for await (const _ of event.rows({ fetch: downloadStub(NDJSON) })) { /* unreachable */ }
  }, /no sha256/)
})

test('rows reads an unchecked file when verification is waived', async () => {
  const { payload, headers, now } = delivery(manifest(''))
  const event = await webhooks.parse(payload, headers, SECRET, { now })

  const rows = []
  for await (const row of event.rows({ fetch: downloadStub(NDJSON), verifyChecksum: false })) {
    rows.push(row)
  }

  assert.deepEqual(rows, [{ id: 'con_1' }, { id: 'con_2' }])
})

test('a failed download surfaces as a verification error', async () => {
  const { payload, headers, now } = delivery(manifest())
  const event = await webhooks.parse(payload, headers, SECRET, { now })

  await assert.rejects(async () => {
    for await (const _ of event.rows({ fetch: downloadStub('', 403) })) { /* unreachable */ }
  }, /HTTP 403/)
})
