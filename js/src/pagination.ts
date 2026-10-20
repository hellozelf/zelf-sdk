import { NotFoundError } from './errors.js'
import type { Envelope } from './transport.js'

export interface PageMeta {
  logId: string
  timestamp: string
  itemCount: number
  page: number
  next: number | null
  previous: number | null
  appliedFilters: Record<string, unknown>
}

export type Fetcher<T> = (page: number) => Promise<Envelope<T>>

/** One page of results plus the envelope metadata that came with it. */
export class Page<T> implements Iterable<T> {
  readonly results: T[]
  readonly meta: PageMeta

  // Type stripping cannot erase a parameter property.
  private readonly fetchPage?: Fetcher<T>

  constructor(envelope: Envelope<T>, fetchPage?: Fetcher<T>) {
    this.fetchPage = fetchPage
    this.results = rows(envelope)
    this.meta = {
      logId: envelope.log_id,
      timestamp: envelope.timestamp,
      itemCount: envelope.item_count,
      page: envelope.page,
      next: envelope.next ?? null,
      previous: envelope.previous ?? null,
      appliedFilters: envelope.applied_filters ?? {},
    }
  }

  get hasNext(): boolean {
    return this.meta.next !== null
  }

  [Symbol.iterator](): Iterator<T> {
    return this.results[Symbol.iterator]()
  }

  async nextPage(): Promise<Page<T> | null> {
    if (!this.fetchPage || this.meta.next === null) return null
    return new Page(await this.fetchPage(this.meta.next), this.fetchPage)
  }

  /**
   * Yield this page and the ones after it.
   *
   * `maxPages` counts this page as the first, so `maxPages: 1` yields only
   * what has already been fetched and makes no further request.
   */
  async *pages(maxPages?: number): AsyncIterableIterator<Page<T>> {
    if (maxPages !== undefined && maxPages < 1) {
      throw new RangeError('maxPages must be 1 or greater.')
    }
    let current: Page<T> | null = this
    let seen = 0
    while (current) {
      yield current
      seen += 1
      if (maxPages !== undefined && seen >= maxPages) return
      current = await current.nextPage()
    }
  }

  /**
   * Walk the remaining pages, yielding one item at a time.
   *
   * `maxPages` bounds how many pages are fetched and `maxItems` how many items
   * come back. Either one stops the walk, so no page is requested once enough
   * items are in hand.
   */
  async *autoPaging(
    limits: { maxPages?: number; maxItems?: number } = {},
  ): AsyncIterableIterator<T> {
    const { maxPages, maxItems } = limits
    if (maxItems !== undefined && maxItems < 1) {
      throw new RangeError('maxItems must be 1 or greater.')
    }
    let produced = 0
    for await (const page of this.pages(maxPages)) {
      for (const item of page.results) {
        yield item
        produced += 1
        if (maxItems !== undefined && produced >= maxItems) return
      }
    }
  }
}

export function rows<T>(envelope: Envelope<T>): T[] {
  const results = envelope.results ?? []
  if (!Array.isArray(results)) {
    throw new TypeError('`results` was not an array; the API response shape changed.')
  }
  return results
}

/**
 * Take the single row out of the envelope.
 *
 * Reads that match nothing come back as 200 with an empty `results` array
 * rather than a 404, so the empty case is raised as a not-found error.
 */
export function one<T>(envelope: Envelope<T>, what: string): T {
  const found = rows(envelope)
  if (found.length === 0) {
    throw new NotFoundError(`No ${what} matched the request.`, {
      status: 404,
      code: 'NOT_FOUND',
      logId: envelope.log_id ?? null,
    })
  }
  return found[0] as T
}
