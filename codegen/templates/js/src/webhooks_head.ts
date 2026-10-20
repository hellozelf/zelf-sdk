import type { WebhookFile, WebhookPush } from './models.js'

export const SIGNATURE_HEADER = 'webhook-signature'
export const TIMESTAMP_HEADER = 'webhook-timestamp'
export const ID_HEADER = 'webhook-id'
export const DEFAULT_TOLERANCE_SECONDS = 300

export class WebhookVerificationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'WebhookVerificationError'
  }
}

export type HeaderBag = Headers | Record<string, string | string[] | undefined>

function readHeader(headers: HeaderBag, name: string): string | null {
  if (typeof (headers as Headers).get === 'function') {
    return (headers as Headers).get(name)
  }
  const lowered = name.toLowerCase()
  for (const [key, value] of Object.entries(headers as Record<string, string | string[] | undefined>)) {
    if (key.toLowerCase() === lowered) return Array.isArray(value) ? (value[0] ?? null) : (value ?? null)
  }
  return null
}

function parseSignature(raw: string): { timestamp: number; digests: string[] } {
  let timestamp: number | null = null
  const digests: string[] = []
  for (const part of raw.split(',')) {
    const [key, ...rest] = part.trim().split('=')
    const value = rest.join('=')
    if (key === 't' && timestamp === null) {
      const parsed = Number(value)
      if (!Number.isInteger(parsed)) {
        throw new WebhookVerificationError('Signature timestamp is not an integer.')
      }
      timestamp = parsed
    } else if (key === 'v1') {
      digests.push(value)
    }
  }
  if (timestamp === null || digests.length === 0) {
    throw new WebhookVerificationError('Signature header is missing a `t` or `v1` component.')
  }
  return { timestamp, digests }
}

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> | null {
  if (hex.length === 0 || hex.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(hex)) return null
  const out = new Uint8Array(new ArrayBuffer(hex.length / 2))
  for (let i = 0; i < out.length; i += 1) out[i] = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16)
  return out
}

function toBytes(payload: Uint8Array | ArrayBuffer | string): Uint8Array<ArrayBuffer> {
  if (typeof payload === 'string') {
    throw new TypeError('payload must be the raw request bytes, not a decoded string.')
  }
  const source = payload instanceof Uint8Array ? payload : new Uint8Array(payload)
  const out = new Uint8Array(new ArrayBuffer(source.byteLength))
  out.set(source)
  return out
}

/**
 * Verify a ZelfAI webhook and return its decoded payload as a plain object.
 *
 * Prefer `parse`, which returns the same thing as a typed WebhookEvent.
 *
 * `payload` must be the exact bytes received. Re-serialising the JSON changes
 * the bytes and the signature will not match.
 *
 * A rotation switches at once: the API signs the next delivery with the new
 * secret only and rejects the old one immediately. An array of secrets is
 * accepted, so both can be held during a rollout.
 *
 * Verification goes through WebCrypto's `subtle.verify`, which compares the MAC
 * in constant time; a wrong signature cannot be recovered from response timing.
 */
export async function verify(
  payload: Uint8Array | ArrayBuffer,
  headers: HeaderBag,
  secret: string | readonly string[],
  options: { toleranceSeconds?: number; now?: number } = {},
): Promise<Record<string, unknown>> {
  const bytes = toBytes(payload)
  const raw = readHeader(headers, SIGNATURE_HEADER)
  if (!raw) throw new WebhookVerificationError('Missing Webhook-Signature header.')

  const { timestamp, digests } = parseSignature(raw)
  const tolerance = options.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS
  if (tolerance > 0) {
    const now = options.now ?? Date.now() / 1000
    const age = Math.abs(now - timestamp)
    if (age > tolerance) {
      throw new WebhookVerificationError(
        `Webhook timestamp is ${Math.round(age)}s away from now, outside the ` +
          `${tolerance}s tolerance. Treating it as a replay.`,
      )
    }
  }

  const secrets = typeof secret === 'string' ? [secret] : [...secret]
  if (secrets.length === 0) throw new Error('At least one signing secret is required.')

  const prefix = new TextEncoder().encode(`${timestamp}.`)
  const signed = new Uint8Array(new ArrayBuffer(prefix.byteLength + bytes.byteLength))
  signed.set(prefix)
  signed.set(bytes, prefix.byteLength)
  let matched = false
  for (const candidate of secrets) {
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(candidate),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify'],
    )
    for (const digest of digests) {
      const signature = hexToBytes(digest)
      if (!signature) continue
      if (await crypto.subtle.verify('HMAC', key, signature, signed)) matched = true
    }
  }
  if (!matched) throw new WebhookVerificationError('No signature matched the supplied secret(s).')

  let body: unknown
  try {
    body = JSON.parse(new TextDecoder().decode(bytes))
  } catch {
    throw new WebhookVerificationError('Webhook body is not valid JSON.')
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    throw new WebhookVerificationError('Webhook body is not a JSON object.')
  }
  return body as Record<string, unknown>
}

/** A delivery whose signature has already been checked. */
export class WebhookEvent {
  /** The payload exactly as it arrived, including fields the SDK predates. */
  readonly raw: Record<string, unknown>
  readonly payload: WebhookPush

  constructor(raw: Record<string, unknown>) {
    this.raw = raw
    this.payload = raw as unknown as WebhookPush
  }

  get id(): string {
    return this.payload.id
  }

  /** The wire value, which may be newer than this SDK's EventType. */
  get type(): string {
    return this.payload.type
  }

  /** The declared event type, or null for one the SDK predates. */
  get eventType(): EventType | null {
    return isEventType(this.payload.type) ? this.payload.type : null
  }

  get subscriptionId(): string {
    return this.payload.subscription_id
  }

  get livemode(): boolean {
    return Boolean(this.payload.livemode)
  }

  get deliveredAt(): Date {
    return new Date(this.payload.delivered_at * 1000)
  }

  get deliveryMode(): string {
    return this.payload.delivery_mode
  }

  /** Downloadable snapshot files. Populated in `manifest` mode only. */
  get files(): WebhookFile[] {
    return (this.payload.data?.files ?? []) as WebhookFile[]
  }

  /** Rows carried in the body. Populated in `inline` mode only. */
  get items(): unknown[] {
    return (this.payload.data?.items ?? []) as unknown[]
  }

  get statistics(): unknown {
    return this.payload.data?.statistics
  }

  get itemCount(): number {
    return this.payload.data?.item_count ?? 0
  }

  /**
   * Download the manifest files and yield one decoded row per line.
   *
   * Each `download_url` is signed and expires, so fetch soon after delivery.
   * With `verifyChecksum` the published SHA-256 is recomputed over the body, and
   * a mismatch or a missing digest throws before any row is yielded.
   */
  async *rows(
    options: { fetch?: typeof globalThis.fetch; verifyChecksum?: boolean } = {},
  ): AsyncIterableIterator<Record<string, unknown>> {
    const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis)
    const verifyChecksum = options.verifyChecksum ?? true

    for (const handle of this.files) {
      const response = await doFetch(handle.download_url)
      if (!response.ok) {
        throw new WebhookVerificationError(
          `Downloading ${handle.download_url} failed with HTTP ${response.status}.`,
        )
      }
      const body = new Uint8Array(await response.arrayBuffer())
      if (verifyChecksum) {
        if (!handle.sha256) {
          throw new WebhookVerificationError(
            `The manifest published no sha256 for ${handle.download_url}, so the file ` +
              'cannot be verified. Pass verifyChecksum: false to read it unchecked.',
          )
        }
        const digest = await sha256Hex(body)
        if (digest !== handle.sha256) {
          throw new WebhookVerificationError(
            `Downloaded file digest ${digest} does not match the published ${handle.sha256}.`,
          )
        }
      }
      for (const line of new TextDecoder().decode(body).split('\n')) {
        if (line.trim()) yield JSON.parse(line) as Record<string, unknown>
      }
    }
  }
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const copy = new Uint8Array(new ArrayBuffer(bytes.byteLength))
  copy.set(bytes)
  const digest = await crypto.subtle.digest('SHA-256', copy)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Verify a delivery and return it as a typed WebhookEvent. */
export async function parse(
  payload: Uint8Array | ArrayBuffer,
  headers: HeaderBag,
  secret: string | readonly string[],
  options: { toleranceSeconds?: number; now?: number } = {},
): Promise<WebhookEvent> {
  return new WebhookEvent(await verify(payload, headers, secret, options))
}

export type Listener = (event: WebhookEvent) => unknown | Promise<unknown>

/**
 * Verify a delivery once, then route it to the listener for its type.
 *
 * Framework agnostic: hand it the raw body and the request headers from
 * whatever server is in front of it.
 *
 *     const handler = new WebhookHandler(secret)
 *     handler.on(CONTENT_SNAPSHOT, async (event) => {
 *       for await (const row of event.rows()) { ... }
 *     })
 */
export class WebhookHandler {
  readonly #secret: string | readonly string[]
  readonly #toleranceSeconds: number
  readonly #listeners = new Map<string, Listener[]>()
  #fallback: Listener | null = null

  constructor(
    secret: string | readonly string[],
    options: { toleranceSeconds?: number } = {},
  ) {
    this.#secret = secret
    this.#toleranceSeconds = options.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS
  }

  /** Register a listener for one or more event types. */
  on(eventTypes: EventType | string | readonly (EventType | string)[], listener: Listener): this {
    const names = Array.isArray(eventTypes) ? [...eventTypes] : [eventTypes as string]
    if (names.length === 0) throw new RangeError('Pass at least one event type to listen for.')
    const unknown = names.filter((name) => !isEventType(name))
    if (unknown.length > 0) {
      throw new RangeError(
        `Unknown event type(s) ${unknown.join(', ')}. ` +
          `Known types: ${Object.values(EventType).join(', ')}.`,
      )
    }
    for (const name of names) {
      this.#listeners.set(name, [...(this.#listeners.get(name) ?? []), listener])
    }
    return this
  }

  /** Register the listener used when no type specific one matched. */
  onAny(listener: Listener): this {
    this.#fallback = listener
    return this
  }

  /**
   * Verify, then call every listener registered for the event type.
   *
   * Throws WebhookVerificationError before any listener runs if the signature,
   * timestamp, or body does not check out.
   */
  async handle(
    payload: Uint8Array | ArrayBuffer,
    headers: HeaderBag,
    options: { now?: number } = {},
  ): Promise<unknown[]> {
    const event = await parse(payload, headers, this.#secret, {
      toleranceSeconds: this.#toleranceSeconds,
      now: options.now,
    })
    const listeners = this.#listeners.get(event.type)
    if (!listeners || listeners.length === 0) {
      return this.#fallback ? [await this.#fallback(event)] : []
    }
    const results: unknown[] = []
    for (const listener of listeners) results.push(await listener(event))
    return results
  }
}
