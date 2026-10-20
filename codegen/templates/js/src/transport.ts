import {
  ZelfAPIError,
  ZelfConnectionError,
  ZelfTimeoutError,
  statusError,
  type ApiErrorBody,
} from './errors.js'
import { VERSION } from './version.js'

export const DEFAULT_BASE_URL = 'https://api.hellozelf.com'
/** Read when no base URL is passed explicitly. */
export const BASE_URL_ENV = 'ZELF_BASE_URL'

const RETRY_STATUSES = new Set([429, 500, 502, 503, 504])
// The API documents no Idempotency-Key header, so a retried write could create
// a second analysis, vetting, or sync job. Writes are retried only on request.
const RETRY_SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const MAX_BACKOFF_MS = 8000

export interface Envelope<T> {
  log_id: string
  timestamp: string
  applied_filters?: Record<string, unknown>
  results: T[]
  item_count: number
  page: number
  next: number | null
  previous: number | null
}

export interface ClientOptions {
  apiKey?: string
  baseUrl?: string
  timeoutMs?: number
  maxRetries?: number
  retryWrites?: boolean
  defaultHeaders?: Record<string, string>
  fetch?: typeof globalThis.fetch
}

export interface RequestOptions {
  pathParams?: Record<string, string | number>
  query?: Record<string, unknown>
  body?: unknown
  signal?: AbortSignal
}

export type QueryValue = string | number | boolean | Date | null | undefined

export function encodeQuery(query: Record<string, unknown>): URLSearchParams {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue
    const items = Array.isArray(value) ? value : [value]
    for (const item of items) {
      if (item === null || item === undefined) continue
      params.append(key, item instanceof Date ? item.toISOString() : String(item))
    }
  }
  return params
}

export function backoffMs(attempt: number, response: Response | null): number {
  const header = response?.headers.get('retry-after')
  if (header) {
    const seconds = Number(header)
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 60_000)
  }
  return Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt) * (0.5 + Math.random() / 2)
}

function shouldRetry(method: string, response: Response | null, retryWrites: boolean): boolean {
  if (!RETRY_SAFE_METHODS.has(method.toUpperCase()) && !retryWrites) return false
  return response === null || RETRY_STATUSES.has(response.status)
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export class Transport {
  readonly baseUrl: string
  readonly timeoutMs: number
  readonly maxRetries: number
  readonly retryWrites: boolean
  readonly #apiKey: string
  readonly #headers: Record<string, string>
  readonly #fetch: typeof globalThis.fetch

  constructor(options: ClientOptions = {}) {
    const apiKey = options.apiKey ?? readEnv('ZELF_API_KEY')
    if (!apiKey) {
      throw new Error('apiKey is required. Pass it directly or set ZELF_API_KEY.')
    }
    if ((options.maxRetries ?? 2) < 0) throw new Error('maxRetries must be zero or greater.')

    this.#apiKey = apiKey
    this.baseUrl = (options.baseUrl ?? readEnv(BASE_URL_ENV) ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.timeoutMs = options.timeoutMs ?? 60_000
    this.maxRetries = options.maxRetries ?? 2
    this.retryWrites = options.retryWrites ?? false
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis)
    // The client's own key goes on last and a caller's copy of it is dropped
    // whatever its casing, so exactly one key reaches the wire.
    this.#headers = {
      accept: 'application/json',
      'user-agent': `zelf-node/${VERSION}`,
      ...Object.fromEntries(
        Object.entries(options.defaultHeaders ?? {}).filter(
          ([name]) => name.toLowerCase() !== 'x-api-key',
        ),
      ),
      'x-api-key': apiKey,
    }
  }

  /** Never prints the key; `JSON.stringify(client)` cannot reach it either. */
  toJSON(): Record<string, unknown> {
    return { baseUrl: this.baseUrl, apiKey: '***' }
  }

  buildUrl(path: string, pathParams: Record<string, string | number> = {}, query: Record<string, unknown> = {}): string {
    let resolved = path
    for (const [name, value] of Object.entries(pathParams)) {
      if (value === null || value === undefined || value === '') {
        throw new Error(`${name} is required and must not be empty.`)
      }
      resolved = resolved.replace(`{${name}}`, encodeURIComponent(String(value)))
    }
    const params = encodeQuery(query)
    const search = params.toString()
    return `${this.baseUrl}${resolved}${search ? `?${search}` : ''}`
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<Envelope<T>> {
    const url = this.buildUrl(path, options.pathParams, options.query)
    const headers = { ...this.#headers }
    if (options.body !== undefined) headers['content-type'] = 'application/json'

    let lastError: Error | null = null
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      let response: Response | null = null
      const timer = AbortSignal.timeout(this.timeoutMs)
      try {
        response = await this.#fetch(url, {
          method,
          headers,
          body: options.body === undefined ? undefined : JSON.stringify(options.body),
          signal: options.signal ? AbortSignal.any([options.signal, timer]) : timer,
        })
        if (response.ok) return (await readEnvelope<T>(response)) as Envelope<T>
        lastError = await parseError(response)
      } catch (cause) {
        // A malformed body is the API answering badly, not the network failing.
        if (cause instanceof ZelfAPIError) throw cause
        lastError = toTransportError(cause)
        if (options.signal?.aborted) throw lastError
      }
      if (attempt === this.maxRetries || !shouldRetry(method, response, this.retryWrites)) break
      await sleep(backoffMs(attempt, response))
    }
    throw lastError ?? new ZelfConnectionError()
  }
}

async function readEnvelope<T>(response: Response): Promise<Envelope<T> | Record<string, never>> {
  if (response.status === 204) return {}
  const text = await response.text()
  if (!text) return {}
  let body: unknown
  try {
    body = JSON.parse(text)
  } catch {
    throw new ZelfAPIError('The API returned a response that is not valid JSON.', {
      status: response.status,
      response,
    })
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    throw new ZelfAPIError('The API returned a response envelope that is not an object.', {
      status: response.status,
      response,
    })
  }
  return body as Envelope<T>
}

async function parseError(response: Response): Promise<ZelfAPIError> {
  let body: ApiErrorBody = {}
  try {
    body = (await response.clone().json()) as ApiErrorBody
  } catch {
    body = {}
  }
  return statusError(response.status, {
    message: body.error?.message ?? `HTTP ${response.status} from the ZelfAI API.`,
    code: body.error?.code ?? null,
    details: body.error?.details ?? {},
    logId: body.log_id ?? null,
    response,
  })
}

function toTransportError(cause: unknown): Error {
  const name = (cause as { name?: string })?.name
  if (name === 'TimeoutError') return new ZelfTimeoutError()
  if (name === 'AbortError') return new ZelfConnectionError('The request was aborted.')
  const message = cause instanceof Error ? cause.message : String(cause)
  return new ZelfConnectionError(message || undefined)
}

function readEnv(name: string): string | undefined {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
  return env?.[name]
}
