import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runId } from '../run/brand'
import { runFeed, type Connection, type FeedClock, type FeedItem, type FeedOptions, type FetchLike } from './feed'

const SUCCESS = runId('run_01JB8')
const FAILURE = runId('run_01JB9')

interface Recorded {
  readonly accept: string | null
  readonly after: number | null
  readonly lastEventId: string | null
}

interface StreamHandle {
  push(raw: unknown): void
  chunk(text: string): void
  comment(): void
  close(): void
  readonly cancelled: boolean
}

interface FakeApi {
  readonly fetch: FetchLike
  readonly requests: Recorded[]
  readonly streams: StreamHandle[]
  /** The server has emitted events up to this seq. */
  emitted: number
  /** Seqs the JSON page leaves out, to fake a server hole. */
  readonly hidden: Set<number>
  dateHeader: string | null
  failNext(count: number): void
  /** The next `count` requests answer this HTTP status with a problem body. */
  answerNext(status: number, count: number): void
}

interface Raw {
  readonly seq: number
}

const encoder = new TextEncoder()
const frame = (raw: Raw) => `id: ${raw.seq}\nevent: activity\ndata: ${JSON.stringify(raw)}\n\n`

function fakeApi(recording: readonly Raw[], emitted: number): FakeApi {
  let failures = 0
  let answers: { status: number; count: number } | null = null
  const api: FakeApi = {
    requests: [],
    streams: [],
    emitted,
    hidden: new Set(),
    dateHeader: null,
    failNext: (count) => void (failures += count),
    answerNext: (status, count) => void (answers = { status, count }),
    fetch: (input, init) => {
      if (failures > 0) {
        failures -= 1
        return Promise.reject(new TypeError('network down'))
      }
      const headers = new Headers(init?.headers)
      const url = new URL(input, 'http://portal.test')
      const after = url.searchParams.get('after')
      const accept = headers.get('Accept')
      api.requests.push({ accept, after: after === null ? null : Number(after), lastEventId: headers.get('Last-Event-ID') })
      if (answers && answers.count > 0) {
        answers.count -= 1
        return Promise.resolve(new Response(JSON.stringify({ message: 'There is no such run.' }), { status: answers.status }))
      }
      const responseHeaders = api.dateHeader ? { Date: api.dateHeader } : {}
      if (accept === 'text/event-stream') {
        const stream = openStream()
        api.streams.push(stream)
        return Promise.resolve(new Response(stream.body, { status: 200, headers: responseHeaders }))
      }
      const from = Number(after)
      const events = recording.filter((raw) => raw.seq > from && raw.seq <= api.emitted && !api.hidden.has(raw.seq))
      return Promise.resolve(new Response(JSON.stringify({ events }), { status: 200, headers: responseHeaders }))
    },
  }
  return api
}

function openStream(): StreamHandle & { body: ReadableStream<Uint8Array> } {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined
  const handle = {
    cancelled: false,
    body: new ReadableStream<Uint8Array>({
      start: (c) => void (controller = c),
      cancel: () => void (handle.cancelled = true),
    }),
    chunk: (text: string) => controller?.enqueue(encoder.encode(text)),
    push: (raw: unknown) => handle.chunk(frame(raw as Raw)),
    comment: () => handle.chunk(': keep-alive\n'),
    close: () => controller?.close(),
  }
  return handle
}

function raw(recording: readonly Raw[], seq: number): Raw {
  const found = recording.find((item) => item.seq === seq)
  if (!found) throw new Error(`no seq ${seq} in the recording`)
  return found
}

const clock: FeedClock = {
  after: (ms, fn) => {
    const timer = setTimeout(fn, ms)
    return () => clearTimeout(timer)
  },
  epochNow: () => Date.now(),
}

type Feed = AsyncGenerator<FeedItem>

function start(api: FakeApi, options: Partial<Pick<FeedOptions, 'runId' | 'after' | 'signal' | 'random'>> = {}): Feed {
  return runFeed({
    runId: options.runId ?? SUCCESS,
    fetch: api.fetch,
    clock,
    after: options.after ?? 0,
    signal: options.signal ?? new AbortController().signal,
    random: options.random ?? (() => 0),
  })
}

async function next(feed: Feed): Promise<FeedItem> {
  const result = await feed.next()
  if (result.done) throw new Error('the feed finished early')
  return result.value
}

async function take(feed: Feed, count: number): Promise<FeedItem[]> {
  const items: FeedItem[] = []
  for (let i = 0; i < count; i += 1) items.push(await next(feed))
  return items
}

/** A pull that reports whether it has resolved yet, for assertions on what has not happened. */
function pull(feed: Feed): { readonly settled: boolean; readonly result: Promise<FeedItem> } {
  let settled = false
  const result = next(feed).finally(() => void (settled = true))
  return {
    get settled() {
      return settled
    },
    result,
  }
}

const connection = (c: Connection): FeedItem => ({ type: 'connection', connection: c })
const seqs = (item: FeedItem): number[] => (item.type === 'events' ? item.events.map((event) => event.seq) : [])
const range = (from: number, to: number): number[] => Array.from({ length: to - from + 1 }, (_, i) => from + i)
const flush = () => vi.advanceTimersByTimeAsync(0)

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('runFeed', () => {
  it('yields the backlog page as one item, then follows live with Last-Event-ID', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api)
    expect(await next(feed)).toEqual(connection({ is: 'connecting' }))
    const backlog = await next(feed)
    expect(backlog).toMatchObject({ type: 'events', origin: 'backlog' })
    expect(seqs(backlog)).toEqual(range(1, 17))
    expect(await next(feed)).toEqual(connection({ is: 'live' }))
    expect(api.requests).toEqual([
      { accept: 'application/json', after: 0, lastEventId: null },
      { accept: 'text/event-stream', after: null, lastEventId: '17' },
    ])
    api.emitted = 18
    api.streams[0]?.push(raw(success, 18))
    const live = await next(feed)
    expect(live).toMatchObject({ type: 'events', origin: 'live' })
    expect(seqs(live)).toEqual([18])
  })

  it('drops frames at or below the last seq it yielded', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api)
    await take(feed, 3)
    for (const seq of [17, 18, 18, 19]) api.streams[0]?.push(raw(success, seq))
    api.streams[0]?.push(raw(success, 20))
    expect((await take(feed, 3)).map(seqs)).toEqual([[18], [19], [20]])
  })

  it('fills a gap from the JSON page before yielding the frame that revealed it', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api, { after: 17 })
    expect(await take(feed, 2)).toEqual([connection({ is: 'connecting' }), connection({ is: 'live' })])
    api.emitted = 21
    api.streams[0]?.push(raw(success, 18))
    api.streams[0]?.push(raw(success, 21))
    const items = await take(feed, 3)
    expect(items.map(seqs)).toEqual([[18], [19, 20], [21]])
    expect(items.every((item) => item.type === 'events' && item.origin === 'live')).toBe(true)
    expect(api.requests).toContainEqual({ accept: 'application/json', after: 18, lastEventId: null })
  })

  it('reconnects when a page has a hole, rather than yielding a gap', async () => {
    const api = fakeApi(success, 17)
    api.hidden.add(6)
    const feed = start(api)
    expect(await take(feed, 2)).toEqual([
      connection({ is: 'connecting' }),
      connection({ is: 'reconnecting', attempt: 1, inMs: 500 }),
    ])
  })

  it('reconnects when the gap fill does not reach the frame, rather than yielding a gap', async () => {
    const api = fakeApi(success, 17)
    api.hidden.add(20)
    const feed = start(api, { after: 17 })
    await take(feed, 2)
    api.emitted = 21
    api.streams[0]?.push(raw(success, 18))
    api.streams[0]?.push(raw(success, 21))
    const items = await take(feed, 2)
    expect(items.map(seqs)).toEqual([[18], []])
    expect(items[1]).toEqual(connection({ is: 'reconnecting', attempt: 1, inMs: 500 }))
  })

  it('resumes after a drop from the last seq it yielded, with no seq repeated', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api)
    const before = await take(feed, 3)
    api.emitted = 19
    api.streams[0]?.push(raw(success, 18))
    api.streams[0]?.push(raw(success, 19))
    before.push(...(await take(feed, 2)))
    api.streams[0]?.close()
    expect(await next(feed)).toEqual(connection({ is: 'reconnecting', attempt: 1, inMs: 500 }))
    const resumed = pull(feed)
    await vi.advanceTimersByTimeAsync(499)
    expect(resumed.settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(await resumed.result).toEqual(connection({ is: 'live' }))
    expect(api.requests.slice(2)).toEqual([
      { accept: 'application/json', after: 19, lastEventId: null },
      { accept: 'text/event-stream', after: null, lastEventId: '19' },
    ])
    api.emitted = 20
    api.streams[1]?.push(raw(success, 20))
    const all = [...before.flatMap(seqs), ...seqs(await next(feed))]
    expect(all).toEqual(range(1, 20))
  })

  it('backs off 500, 1000, 2000, 4000, 8000, 15000 and starts again at 500 after a success', async () => {
    const api = fakeApi(success, 17)
    api.failNext(6)
    const feed = start(api)
    expect(await next(feed)).toEqual(connection({ is: 'connecting' }))
    let item = await next(feed)
    for (const [i, inMs] of [500, 1000, 2000, 4000, 8000, 15000].entries()) {
      expect(item).toEqual(connection({ is: 'reconnecting', attempt: i + 1, inMs }))
      const woke = pull(feed)
      await vi.advanceTimersByTimeAsync(inMs - 1)
      expect(woke.settled).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      item = await woke.result
    }
    expect(seqs(item)).toEqual(range(1, 17))
    api.failNext(1)
    expect(await next(feed)).toEqual(connection({ is: 'reconnecting', attempt: 1, inMs: 500 }))
  })

  it('shortens a wait by up to half with the jitter source', async () => {
    const api = fakeApi(success, 17)
    api.failNext(2)
    const feed = start(api, { random: () => 1 })
    expect(await take(feed, 2)).toEqual([
      connection({ is: 'connecting' }),
      connection({ is: 'reconnecting', attempt: 1, inMs: 250 }),
    ])
  })

  it('settles after run_succeeded arrives live, drops the stream and finishes', async () => {
    const api = fakeApi(success, 22)
    const feed = start(api)
    await take(feed, 3)
    api.emitted = 23
    api.streams[0]?.push(raw(success, 23))
    const items = await take(feed, 2)
    expect(seqs(items[0] as FeedItem)).toEqual([23])
    expect(items[1]).toEqual(connection({ is: 'settled' }))
    expect(await feed.next()).toEqual({ done: true, value: undefined })
    expect(api.requests).toHaveLength(2)
    expect(api.streams[0]?.cancelled).toBe(true)
  })

  it('settles straight after a backlog that already ends the run, without opening a stream', async () => {
    const api = fakeApi(success, 23)
    const feed = start(api)
    const items = await take(feed, 3)
    expect(seqs(items[1] as FeedItem)).toEqual(range(1, 23))
    expect(items[2]).toEqual(connection({ is: 'settled' }))
    expect(await feed.next()).toEqual({ done: true, value: undefined })
    expect(api.requests).toHaveLength(1)
  })

  describe('a failed run', () => {
    const retried = {
      ...raw(failure, 12),
      seq: 13,
      ts: '2026-11-04T02:20:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'work', attempt: 2 },
    }

    it('keeps the stream open after run_failed so run_retried still arrives live', async () => {
      const api = fakeApi(failure, 11)
      const feed = start(api, { runId: FAILURE })
      await take(feed, 3)
      api.streams[0]?.push(raw(failure, 12))
      api.streams[0]?.push(retried)
      const items = await take(feed, 2)
      expect(items.map(seqs)).toEqual([[12], [13]])
      expect(items[1]).toMatchObject({ origin: 'live', events: [{ kind: 'run_retried' }] })
      expect(api.requests).toHaveLength(2)
    })

    it('waits 30 s before checking back when the stream closes after run_failed', async () => {
      const api = fakeApi(failure, 11)
      const feed = start(api, { runId: FAILURE })
      await take(feed, 3)
      api.streams[0]?.push(raw(failure, 12))
      api.streams[0]?.close()
      expect(seqs(await next(feed))).toEqual([12])
      expect(await next(feed)).toEqual(connection({ is: 'reconnecting', attempt: 0, inMs: 30_000 }))
      const woke = pull(feed)
      await vi.advanceTimersByTimeAsync(29_999)
      expect(woke.settled).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      expect(await woke.result).toEqual(connection({ is: 'live' }))
      expect(api.requests.slice(2)).toEqual([
        { accept: 'application/json', after: 12, lastEventId: null },
        { accept: 'text/event-stream', after: null, lastEventId: '12' },
      ])
    })
  })

  describe('a 4xx answer is final', () => {
    it('closes for good when the events page answers 404, and never asks again', async () => {
      const api = fakeApi(success, 17)
      api.answerNext(404, 1)
      const feed = start(api)
      expect(await take(feed, 2)).toEqual([
        connection({ is: 'connecting' }),
        connection({ is: 'closed', status: 404, reason: 'not_found' }),
      ])
      expect(await feed.next()).toEqual({ done: true, value: undefined })
      expect(vi.getTimerCount()).toBe(0)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(api.requests).toHaveLength(1)
    })

    it('closes for good when the stream answers 403 after a good backlog', async () => {
      const api = fakeApi(success, 17)
      const feed = start(api)
      expect(await take(feed, 2)).toMatchObject([connection({ is: 'connecting' }), { type: 'events', origin: 'backlog' }])
      api.answerNext(403, 1)
      expect(await next(feed)).toEqual(connection({ is: 'closed', status: 403, reason: 'forbidden' }))
      expect(await feed.next()).toEqual({ done: true, value: undefined })
      expect(api.requests).toHaveLength(2)
    })

    it.each([
      [401, 'signed_out'],
      [422, 'rejected'],
    ] as const)('names the reason for %s as %s', async (status, reason) => {
      const api = fakeApi(success, 17)
      api.answerNext(status, 1)
      const feed = start(api)
      expect(await take(feed, 2)).toEqual([connection({ is: 'connecting' }), connection({ is: 'closed', status, reason })])
    })

    it('keeps backing off on a 500, since the server may come back', async () => {
      const api = fakeApi(success, 17)
      api.answerNext(500, 1)
      const feed = start(api)
      expect(await take(feed, 2)).toEqual([
        connection({ is: 'connecting' }),
        connection({ is: 'reconnecting', attempt: 1, inMs: 500 }),
      ])
      const back = pull(feed)
      await vi.advanceTimersByTimeAsync(500)
      expect(seqs(await back.result)).toEqual(range(1, 17))
    })
  })

  it('yields an unknown kind as an opaque event at its seq and continues', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api)
    await take(feed, 3)
    api.streams[0]?.push({ ...raw(success, 18), kind: 'agent_left', data: { agent: 'release_checker' } })
    api.streams[0]?.push(raw(success, 19))
    const items = await take(feed, 2)
    expect(items[0]).toMatchObject({ events: [{ seq: 18, kind: 'opaque', declaredKind: 'agent_left' }] })
    expect(seqs(items[1] as FeedItem)).toEqual([19])
  })

  it.each([
    ['bad JSON', 'id: 18\nevent: activity\ndata: not json\n\n'],
    ['a broken envelope', `id: 18\nevent: activity\ndata: ${JSON.stringify({ ...raw(success, 18), seq: 'x' })}\n\n`],
    ['another event name', `id: 18\nevent: ping\ndata: ${JSON.stringify(raw(success, 18))}\n\n`],
  ])('skips a frame with %s and reads the next one', async (_name, text) => {
    const api = fakeApi(success, 17)
    const feed = start(api)
    await take(feed, 3)
    api.streams[0]?.chunk(text)
    api.streams[0]?.push(raw(success, 18))
    expect(seqs(await next(feed))).toEqual([18])
    expect(api.requests).toHaveLength(2)
  })

  it('treats 45 s without bytes as a dead socket, but keep-alive comments count as bytes', async () => {
    const api = fakeApi(success, 17)
    const feed = start(api, { after: 17 })
    await take(feed, 2)
    const idle = pull(feed)
    await vi.advanceTimersByTimeAsync(15_000)
    api.streams[0]?.comment()
    await flush()
    await vi.advanceTimersByTimeAsync(15_000)
    api.streams[0]?.comment()
    await flush()
    await vi.advanceTimersByTimeAsync(44_999)
    expect(idle.settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(await idle.result).toEqual(connection({ is: 'reconnecting', attempt: 1, inMs: 500 }))
    expect(api.streams[0]?.cancelled).toBe(true)
    const back = pull(feed)
    await vi.advanceTimersByTimeAsync(500)
    expect(await back.result).toEqual(connection({ is: 'live' }))
    expect(api.requests.slice(2)).toEqual([
      { accept: 'application/json', after: 17, lastEventId: null },
      { accept: 'text/event-stream', after: null, lastEventId: '17' },
    ])
  })

  describe('the Date header', () => {
    const NOW = Date.UTC(2026, 10, 3, 2, 14, 0)
    const serverTimes = (items: readonly FeedItem[]) => items.filter((item) => item.type === 'server_time')

    it('yields the server clock offset once, from the first page', async () => {
      vi.setSystemTime(NOW)
      const api = fakeApi(success, 17)
      api.dateHeader = new Date(NOW + 4000).toUTCString()
      const feed = start(api)
      const items = await take(feed, 4)
      expect(serverTimes(items)).toEqual([{ type: 'server_time', offsetMs: 4000 }])
      api.streams[0]?.close()
      expect(await next(feed)).toMatchObject({ connection: { is: 'reconnecting' } })
      const again = pull(feed)
      await vi.advanceTimersByTimeAsync(500)
      expect(serverTimes([await again.result])).toEqual([])
    })

    it.each([
      ['missing', null],
      ['25 h ahead', new Date(NOW + 25 * 3_600_000).toUTCString()],
      ['25 h behind', new Date(NOW - 25 * 3_600_000).toUTCString()],
    ])('yields nothing when the header is %s', async (_name, header) => {
      vi.setSystemTime(NOW)
      const api = fakeApi(success, 17)
      api.dateHeader = header
      const feed = start(api)
      const items = await take(feed, 3)
      expect(serverTimes(items)).toEqual([])
      expect(items[2]).toEqual(connection({ is: 'live' }))
    })
  })

  describe('abort', () => {
    it('ends the feed mid-stream without further items or requests', async () => {
      const api = fakeApi(success, 17)
      const controller = new AbortController()
      const feed = start(api, { signal: controller.signal })
      await take(feed, 3)
      const pending = feed.next()
      controller.abort()
      expect(await pending).toEqual({ done: true, value: undefined })
      expect(api.requests).toHaveLength(2)
      expect(api.streams[0]?.cancelled).toBe(true)
    })

    it('ends the feed mid-backoff and cancels the timer', async () => {
      const api = fakeApi(success, 17)
      api.failNext(1)
      const controller = new AbortController()
      const feed = start(api, { signal: controller.signal })
      await take(feed, 2)
      const pending = feed.next()
      controller.abort()
      expect(await pending).toEqual({ done: true, value: undefined })
      expect(vi.getTimerCount()).toBe(0)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(api.requests).toHaveLength(0)
    })
  })
})
