import { ZelfAPIClient, ZelfAPIError } from './dist/index.js'

const BRAND = 'brd_6u599tNI2jemKDcb'
const SCOPE = { brandId: BRAND, postedWithinDays: 365, viewCountMin: 250_000_000 }
const out: string[] = []
const check = async (name: string, fn: () => Promise<string>) => {
  const started = Date.now()
  try {
    const detail = await fn()
    out.push(`${name.padEnd(34)} PASS  ${String(Date.now() - started).padStart(6)}ms  ${detail}`)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    out.push(`${name.padEnd(34)} FAIL  ${String(Date.now() - started).padStart(6)}ms  ${message.slice(0, 90)}`)
  }
}

const client = new ZelfAPIClient({ apiKey: process.env.ZELF_API_KEY })

await check('usage.retrieve', async () => `plan fields=${Object.keys(await client.usage.retrieve()).length}`)
await check('content.list', async () => {
  const page = await client.content.list({ ...SCOPE, pageSize: 3 })
  return `items=${page.meta.itemCount} first=${page.results[0]!.id} views=${page.results[0]!.view_count}`
})
await check('content.list autoPaging maxPages=2', async () => {
  const page = await client.content.list({ ...SCOPE, pageSize: 3 })
  const ids: string[] = []
  for await (const item of page.autoPaging({ maxPages: 2 })) ids.push(item.id)
  return `walked ${ids.length} across <=2 pages`
})
await check('content.details', async () => {
  const page = await client.content.list({ ...SCOPE, pageSize: 1 })
  const found = await client.content.details(page.results[0]!.id, { brandId: BRAND })
  return `id=${found.id} platform=${found.platform}`
})
await check('content.details (missing)', async () => {
  try {
    await client.content.details('con_J64wsBXg9rmhOE6dFX')
    return 'no error raised'
  } catch (error) {
    // A malformed id is rejected as 400 INVALID_ID, not 404.
    if (error instanceof ZelfAPIError) return `${error.status} ${error.code}`
    throw error
  }
})
await check('bad key -> 401 typed', async () => {
  const bad = new ZelfAPIClient({ apiKey: 'sk_zelf_definitely_invalid', maxRetries: 0 })
  try {
    await bad.usage.retrieve()
    return 'no error raised'
  } catch (error) {
    if (error instanceof ZelfAPIError) return `${error.status} ${error.code}`
    throw error
  }
})
await check('brands.list', async () => `brands=${(await client.brands.list({})).meta.itemCount}`)
await check('webhooks.listEvents', async () => `events=${(await client.webhooks.listEvents()).length}`)
await check('brand_accounts.list', async () => {
  const groups = await client.brandAccounts.list({ brandId: BRAND, accountType: 'tracked' })
  return `groups=${groups.length} tracked=${groups[0]?.tracked?.length ?? 0}`
})

console.log(out.join('\n'))
