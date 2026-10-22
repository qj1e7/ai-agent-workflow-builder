import createClient from 'openapi-fetch'
import type { paths } from './schema'

export type ApiClient = ReturnType<typeof createClient<paths>>

/** fetchImpl must already sign requests: see authorizedFetch in session.ts. */
export function createApiClient(fetchImpl: typeof fetch, baseUrl = ''): ApiClient {
  return createClient<paths>({ baseUrl, fetch: fetchImpl })
}

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(messageFrom(body) ?? `The platform answered ${status}.`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function messageFrom(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null) return undefined
  const { message, detail } = body as { message?: unknown; detail?: unknown }
  if (typeof message === 'string') return message
  return typeof detail === 'string' ? detail : undefined
}

interface Settled<T> {
  data?: T
  error?: unknown
  response: Response
}

export function unwrap<T>({ data, error, response }: Settled<T>): T {
  if (!response.ok || data === undefined) throw new ApiError(response.status, error)
  return data
}
