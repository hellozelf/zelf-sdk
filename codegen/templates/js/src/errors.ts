export interface ApiErrorBody {
  log_id?: string
  timestamp?: string
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
}

export class ZelfError extends Error {
  constructor(message: string) {
    super(message)
    this.name = new.target.name
  }
}

export class ZelfConnectionError extends ZelfError {
  constructor(message = 'Could not reach the Zelf API.') {
    super(message)
  }
}

export class ZelfTimeoutError extends ZelfConnectionError {
  constructor(message = 'Request to the Zelf API timed out.') {
    super(message)
  }
}

/** The field-level reasons the API gave, as one readable clause. */
export function renderDetails(details: Record<string, unknown> | null | undefined): string {
  if (!details) return ''
  return Object.entries(details)
    .map(([field, reasons]) =>
      `${field}: ${Array.isArray(reasons) ? reasons.join(' ') : String(reasons)}`,
    )
    .join(' ')
}

export class ZelfAPIError extends ZelfError {
  readonly status: number
  readonly code: string | null
  readonly details: Record<string, unknown>
  readonly logId: string | null
  readonly response: Response | null

  constructor(
    message: string,
    options: {
      status: number
      code?: string | null
      details?: Record<string, unknown>
      logId?: string | null
      response?: Response | null
    },
  ) {
    super(message)
    this.status = options.status
    this.code = options.code ?? null
    this.details = options.details ?? {}
    this.logId = options.logId ?? null
    this.response = options.response ?? null
  }

  override toString(): string {
    const parts = [String(this.status), this.code, this.message].filter(Boolean)
    // The message alone says a request was refused but never which field or
    // which limit, and that is the part a caller can act on.
    const detail = renderDetails(this.details)
    if (detail) parts.push(detail)
    return this.logId ? `${parts.join(' ')} (log_id=${this.logId})` : parts.join(' ')
  }
}
