import assert from 'node:assert/strict'
import { test } from 'node:test'

import { ZelfAPIClient, AuthenticationError, RateLimitError } from '../dist/index.js'

const BASE = process.env.ZELF_BASE_URL ?? 'https://sandbox-api.hellozelf.com'
const KEY = process.env.ZELF_API_KEY ?? 'sk_zelf_sandbox_demo'

const client = new ZelfAPIClient({ apiKey: KEY, baseUrl: BASE })

test('usage decodes', async () => {
  assert.ok(await client.usage.retrieve())
})

test('a page decodes every row', async () => {
  const page = await client.content.list({ pageSize: 2 })
  assert.equal(page.meta.itemCount, 2)
  for (const row of page.results) assert.match(row.id, /^con_/)
})

test('auto paging stops at the bound', async () => {
  const page = await client.content.list({ pageSize: 2 })
  const rows = []
  for await (const row of page.autoPaging({ maxPages: 2 })) rows.push(row)
  assert.equal(rows.length, 4)
})

test('a bad key raises the typed error', async () => {
  const bad = new ZelfAPIClient({ apiKey: 'sk_zelf_' + '9'.repeat(64), baseUrl: BASE, maxRetries: 0 })
  await assert.rejects(
    () => bad.usage.retrieve(),
    (error: unknown) =>
      error instanceof AuthenticationError &&
      error.status === 401 &&
      error.code === 'INVALID_API_KEY',
  )
})

test('a rate limit is retried then surfaced', async () => {
  const throttled = new ZelfAPIClient({
    apiKey: KEY,
    baseUrl: BASE,
    maxRetries: 1,
    defaultHeaders: { 'x-sandbox-force-error': 'RATE_LIMIT_EXCEEDED' },
  })
  await assert.rejects(() => throttled.usage.retrieve(), RateLimitError)
})

test('event types are listed', async () => {
  assert.ok((await client.webhooks.listEvents()).length > 0)
})
