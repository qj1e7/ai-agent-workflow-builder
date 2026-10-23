export interface MockRequest {
  readonly method: string
  readonly path: string
  readonly query: URLSearchParams
  readonly headers: Headers
  readonly body: unknown
  readonly signal: AbortSignal | null
}

const PLACEHOLDER_ORIGIN = 'http://mock.portal'

export async function readRequest(input: RequestInfo | URL, init?: RequestInit): Promise<MockRequest> {
  const fromRequest = input instanceof Request ? input : null
  const url = new URL(addressOf(input), PLACEHOLDER_ORIGIN)
  const method = (init?.method ?? fromRequest?.method ?? 'GET').toUpperCase()
  const headers = new Headers(fromRequest?.headers)
  new Headers(init?.headers).forEach((value, name) => headers.set(name, value))
  const raw = method === 'GET' ? '' : await bodyText(fromRequest, init)
  return {
    method,
    path: url.pathname,
    query: url.searchParams,
    headers,
    body: raw ? parseJson(raw) : undefined,
    signal: init?.signal ?? fromRequest?.signal ?? null,
  }
}

function addressOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.href : input.url
}

async function bodyText(request: Request | null, init: RequestInit | undefined): Promise<string> {
  if (typeof init?.body === 'string') return init.body
  return request ? request.text() : ''
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return undefined
  }
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function problem(status: number, detail: string): Response {
  return json(status, { detail })
}

export function invalid(message: string): Response {
  return json(422, { detail: [{ loc: ['body'], msg: message, type: 'value_error' }] })
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
