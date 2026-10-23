import type { Ms, RunId } from '../run/brand'
import { parseEvent, parsePage, type RunEvent } from './parse'
import { createSseParser, textChunks, type SseFrame } from './sse'

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

/** backlog: happened before we were watching, fold silently. live: arrived while watching, animate. */
export type Origin = 'backlog' | 'live'

export type ClosedReason = 'signed_out' | 'forbidden' | 'not_found' | 'rejected'

export type Connection =
  | { readonly is: 'connecting' }
  | { readonly is: 'live' }
  | { readonly is: 'reconnecting'; readonly attempt: number; readonly inMs: Ms }
  /** run_succeeded or run_rejected was yielded. The feed made no further requests and has returned. */
  | { readonly is: 'settled' }
  /** The server refused the run with a 4xx. Asking again would get the same answer, so the feed has returned. */
  | { readonly is: 'closed'; readonly status: number; readonly reason: ClosedReason }

type Events = readonly [RunEvent, ...RunEvent[]]

export type FeedItem =
  /** Contiguous: events[0].seq is exactly one more than the last seq the feed yielded (or `after`). */
  | { readonly type: 'events'; readonly origin: Origin; readonly events: Events }
  | { readonly type: 'connection'; readonly connection: Connection }
  /**
   * From the `Date` header of the first successful response: server epoch ms minus clock.epochNow()
   * at receipt. Yielded once. Not yielded when the header is missing or the offset is absurd (more
   * than 24 h either way).
   */
  | { readonly type: 'server_time'; readonly offsetMs: number }

export interface FeedClock {
  /** Calls fn once after ms. Returns a cancel. setTimeout in the browser (so vitest fake timers and Playwright's page.clock drive it). */
  after(ms: Ms, fn: () => void): () => void
  /** Wall epoch ms, Date.now() in the browser. Only used for the Date header offset. */
  epochNow(): number
}

export interface FeedOptions {
  readonly runId: RunId
  readonly fetch: FetchLike
  readonly clock: FeedClock
  /** Resume point: the last seq the consumer holds. 0 on first load. */
  readonly after: number
  readonly signal: AbortSignal
  /** Jitter source, injected so backoff is deterministic in tests. Default Math.random. */
  readonly random?: () => number
}

export const BACKOFF = { firstMs: 500, factor: 2, capMs: 15_000, jitter: 0.5 } as const
/** The server sends a keep-alive comment every 15 s, so this much silence means a dead connection. */
export const SILENCE_MS: Ms = 45_000
/** After run_failed the stream may close while a retry is still possible. Check back this often. */
export const IDLE_RECHECK_MS: Ms = 30_000

const SETTLING: ReadonlySet<RunEvent['kind']> = new Set(['run_succeeded', 'run_rejected'])
const ABSURD_OFFSET_MS = 24 * 3_600_000

/** The whole of the feed's memory between requests. */
interface FeedState {
  /** The last seq yielded. Every request resumes from here. */
  last: number
  /** Consecutive failures since the last yielded event. */
  attempt: number
  lastKind: RunEvent['kind'] | null
  offsetReported: boolean
}

interface Page {
  readonly events: readonly RunEvent[]
  readonly date: string | null
}

interface Wait {
  readonly attempt: number
  readonly inMs: Ms
}

const connection = (c: Connection): FeedItem => ({ type: 'connection', connection: c })

/** A 4xx answer. Thrown through the request helpers so one catch can end the feed. */
class Refusal extends Error {
  readonly status: number
  constructor(status: number) {
    super(`the server refused the run with ${status}`)
    this.status = status
  }
}

const REASONS: Readonly<Record<number, ClosedReason>> = { 401: 'signed_out', 403: 'forbidden', 404: 'not_found' }

function checkStatus(res: Response, what: string): void {
  if (res.ok) return
  if (res.status >= 400 && res.status < 500) throw new Refusal(res.status)
  throw new Error(`${what} answered ${res.status}`)
}

function contiguous(events: readonly RunEvent[], from: number): boolean {
  return events.every((event, i) => event.seq === from + 1 + i)
}

/** Attempts 1, 2, 3... give 500, 1000, 2000... up to the cap, each shortened by up to half. */
function backoffMs(attempt: number, random: () => number): Ms {
  const base = Math.min(BACKOFF.capMs, BACKOFF.firstMs * BACKOFF.factor ** (attempt - 1))
  return base * (1 - BACKOFF.jitter * random())
}

function serverOffset(dateHeader: string | null, now: number): number | undefined {
  if (dateHeader === null) return undefined
  const offset = Date.parse(dateHeader) - now
  return Number.isNaN(offset) || Math.abs(offset) > ABSURD_OFFSET_MS ? undefined : offset
}

function sleep(clock: FeedClock, ms: Ms, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const wake = () => {
      signal.removeEventListener('abort', wake)
      cancel()
      resolve()
    }
    const cancel = clock.after(ms, wake)
    signal.addEventListener('abort', wake, { once: true })
  })
}

function nonEmpty(events: readonly RunEvent[]): events is Events {
  return events.length > 0
}

/** Records the yield of `events` so that the next request resumes after them. */
function accept(state: FeedState, origin: Origin, events: Events): FeedItem {
  const lastEvent = events[events.length - 1] ?? events[0]
  state.last = lastEvent.seq
  state.lastKind = lastEvent.kind
  state.attempt = 0
  return { type: 'events', origin, events }
}

function readFrame(frame: SseFrame, runId: RunId): RunEvent | undefined {
  if (frame.event !== 'activity') return undefined
  let raw: unknown
  try {
    raw = JSON.parse(frame.data)
  } catch {
    return undefined
  }
  const parsed = parseEvent(raw, runId)
  return parsed.ok ? parsed.event : undefined
}

const eventsUrl = (o: FeedOptions) => `/api/v1/runs/${o.runId}/events`

async function fetchPage(o: FeedOptions, after: number): Promise<Page> {
  const res = await o.fetch(`${eventsUrl(o)}?after=${after}`, { headers: { Accept: 'application/json' }, signal: o.signal })
  checkStatus(res, 'the events page')
  const raw: unknown = await res.json()
  const page = parsePage(raw, o.runId)
  if (!page.ok) throw new Error(page.problem)
  return { events: page.events.filter((event) => event.seq > after), date: res.headers.get('Date') }
}

/** The events strictly between `last` and the live frame at `upTo`, which must fill that gap exactly. */
async function fetchGap(o: FeedOptions, last: number, upTo: number): Promise<Events> {
  const fill = (await fetchPage(o, last)).events.filter((event) => event.seq < upTo)
  if (!nonEmpty(fill) || !contiguous(fill, last) || fill.length !== upTo - last - 1) {
    throw new Error(`the page after ${last} does not fill the gap before ${upTo}`)
  }
  return fill
}

/** closed: the server ended the stream. silent: nothing arrived for SILENCE_MS, so the feed dropped it. */
type StreamEnd = 'closed' | 'silent' | 'settled'

async function* follow(o: FeedOptions, state: FeedState): AsyncGenerator<FeedItem, StreamEnd> {
  const socket = new AbortController()
  const drop = () => socket.abort()
  o.signal.addEventListener('abort', drop, { once: true })
  let silent = false
  let cancelSilence: () => void = () => undefined
  const heard = () => {
    cancelSilence()
    cancelSilence = o.clock.after(SILENCE_MS, () => {
      silent = true
      socket.abort()
    })
  }
  try {
    const res = await o.fetch(eventsUrl(o), {
      headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(state.last) },
      signal: socket.signal,
    })
    checkStatus(res, 'the events stream')
    if (!res.body) throw new Error('the events stream has no body')
    yield connection({ is: 'live' })
    heard()
    const parser = createSseParser()
    for await (const chunk of textChunks(res.body, socket.signal)) {
      heard()
      for (const frame of parser.push(chunk)) {
        const event = readFrame(frame, o.runId)
        if (!event || event.seq <= state.last) continue
        if (event.seq > state.last + 1) yield accept(state, 'live', await fetchGap(o, state.last, event.seq))
        yield accept(state, 'live', [event])
        if (SETTLING.has(event.kind)) return 'settled'
      }
    }
  } catch (error) {
    // A real fetch rejects when its signal aborts, so the silence abort surfaces here too.
    if (!silent) throw error
  } finally {
    cancelSilence()
    o.signal.removeEventListener('abort', drop)
    socket.abort()
  }
  return silent ? 'silent' : 'closed'
}

export async function* runFeed(o: FeedOptions): AsyncGenerator<FeedItem> {
  const state: FeedState = { last: o.after, attempt: 0, lastKind: null, offsetReported: false }
  const random = o.random ?? Math.random
  const failed = (): Wait => {
    state.attempt += 1
    return { attempt: state.attempt, inMs: backoffMs(state.attempt, random) }
  }
  yield connection({ is: 'connecting' })
  while (!o.signal.aborted) {
    let wait: Wait
    try {
      const page = await fetchPage(o, state.last)
      if (!state.offsetReported) {
        state.offsetReported = true
        const offsetMs = serverOffset(page.date, o.clock.epochNow())
        if (offsetMs !== undefined) yield { type: 'server_time', offsetMs }
      }
      if (!contiguous(page.events, state.last)) throw new Error('the events page has a hole')
      if (nonEmpty(page.events)) yield accept(state, 'backlog', page.events)
      if (state.lastKind !== null && SETTLING.has(state.lastKind)) {
        yield connection({ is: 'settled' })
        return
      }
      const end = yield* follow(o, state)
      if (end === 'settled') {
        yield connection({ is: 'settled' })
        return
      }
      // A dead socket is not the server's failure, so its reconnect starts the ladder again.
      if (end === 'silent') state.attempt = 0
      wait = end === 'closed' && state.lastKind === 'run_failed' ? { attempt: 0, inMs: IDLE_RECHECK_MS } : failed()
    } catch (error) {
      if (o.signal.aborted) return
      if (error instanceof Refusal) {
        yield connection({ is: 'closed', status: error.status, reason: REASONS[error.status] ?? 'rejected' })
        return
      }
      wait = failed()
    }
    if (o.signal.aborted) return
    yield connection({ is: 'reconnecting', ...wait })
    await sleep(o.clock, wait.inMs, o.signal)
  }
}
