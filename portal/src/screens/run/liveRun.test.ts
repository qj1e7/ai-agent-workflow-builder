import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it, vi } from 'vitest'
import type { FeedClock, FetchLike } from '../../stream/feed'
import { beatAfter, createLiveRun, MOVE_MS, SMALL_MS, type LiveRunStore } from './liveRun'

interface Raw {
  readonly seq: number
}

interface Stream {
  readonly body: ReadableStream<Uint8Array>
  push(raw: Raw): void
  cancelled: boolean
}

const encoder = new TextEncoder()

function openStream(): Stream {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined
  const stream: Stream = {
    cancelled: false,
    body: new ReadableStream<Uint8Array>({
      start: (c) => void (controller = c),
      cancel: () => void (stream.cancelled = true),
    }),
    push: (raw) => controller?.enqueue(encoder.encode(`id: ${raw.seq}\nevent: activity\ndata: ${JSON.stringify(raw)}\n\n`)),
  }
  return stream
}

function fakeServer(recording: readonly Raw[], stored: number) {
  const server = {
    stored,
    streams: [] as Stream[],
    pages: [] as number[],
    fetch: ((input, init) => {
      const accept = new Headers(init?.headers).get('Accept')
      if (accept === 'text/event-stream') {
        const stream = openStream()
        server.streams.push(stream)
        return Promise.resolve(new Response(stream.body, { status: 200 }))
      }
      const after = Number(new URL(input, 'http://portal.test').searchParams.get('after'))
      server.pages.push(after)
      const events = recording.filter((raw) => raw.seq > after && raw.seq <= server.stored)
      return Promise.resolve(new Response(JSON.stringify({ events }), { status: 200 }))
    }) as FetchLike,
    send(upTo: number) {
      const stream = server.streams.at(-1)
      for (const raw of recording.filter((r) => r.seq > server.stored && r.seq <= upTo)) stream?.push(raw)
      server.stored = upTo
    },
  }
  return server
}

function handClock() {
  let now = 1_000
  let timers: { at: number; fn: () => void }[] = []
  const clock: FeedClock = {
    after(ms, fn) {
      const timer = { at: now + ms, fn }
      timers.push(timer)
      return () => {
        timers = timers.filter((t) => t !== timer)
      }
    },
    epochNow: () => now,
  }
  return {
    clock,
    advance(ms: number) {
      const until = now + ms
      for (let next = timers.sort((a, b) => a.at - b.at)[0]; next && next.at <= until; next = timers.sort((a, b) => a.at - b.at)[0]) {
        timers = timers.filter((t) => t !== next)
        now = next.at
        next.fn()
      }
      now = until
    },
  }
}

function watch(store: LiveRunStore): () => void {
  return store.subscribe(() => undefined)
}

describe('the live run store', () => {
  it('draws the events from before it was watching at once, with no motion', async () => {
    const server = fakeServer(success, 6)
    const { clock } = handClock()
    const store = createLiveRun('run_01JB8', { fetch: server.fetch, clock, paced: () => true })
    const stop = watch(store)
    await vi.waitFor(() => expect(store.getSnapshot().loaded).toBe(true))
    expect(store.getSnapshot().shown.seq).toBe(6)
    expect(store.getSnapshot().loadedUpTo).toBe(6)
    expect(store.getSnapshot().shown).toBe(store.getSnapshot().head)
    stop()
  })

  it('plays a burst of live events one beat at a time', async () => {
    const server = fakeServer(success, 6)
    const time = handClock()
    const store = createLiveRun('run_01JB8', { fetch: server.fetch, clock: time.clock, paced: () => true })
    const stop = watch(store)
    await vi.waitFor(() => expect(store.getSnapshot().connection.is).toBe('live'))
    server.send(15)
    await vi.waitFor(() => expect(store.getSnapshot().head.seq).toBe(15))
    const first = store.getSnapshot().shown.seq
    expect(first).toBeLessThan(15)
    expect(first).toBeGreaterThan(6)
    const seen = [first]
    for (let step = 0; step < 40 && store.getSnapshot().shown.seq < 15; step += 1) {
      time.advance(100)
      seen.push(store.getSnapshot().shown.seq)
    }
    expect(store.getSnapshot().shown.seq).toBe(15)
    expect(new Set(seen).size, 'the page moved in several steps').toBeGreaterThan(3)
    expect(store.getSnapshot().loadedUpTo).toBe(6)
    stop()
  })

  it('does not pace when motion is reduced', async () => {
    const server = fakeServer(success, 6)
    const { clock } = handClock()
    const store = createLiveRun('run_01JB8', { fetch: server.fetch, clock, paced: () => false })
    const stop = watch(store)
    await vi.waitFor(() => expect(store.getSnapshot().connection.is).toBe('live'))
    server.send(15)
    await vi.waitFor(() => expect(store.getSnapshot().shown.seq).toBe(15))
    stop()
  })

  it('stops the stream when the last watcher leaves, and resumes from what it holds', async () => {
    const server = fakeServer(success, 6)
    const { clock } = handClock()
    const store = createLiveRun('run_01JB8', { fetch: server.fetch, clock, paced: () => false })
    const stop = watch(store)
    await vi.waitFor(() => expect(server.streams).toHaveLength(1))
    stop()
    await vi.waitFor(() => expect(server.streams[0]?.cancelled).toBe(true))
    const again = watch(store)
    await vi.waitFor(() => expect(server.pages).toEqual([0, 6]))
    again()
  })

  it('after a restart, plays what comes back as live', async () => {
    const server = fakeServer(success, 6)
    const time = handClock()
    const store = createLiveRun('run_01JB8', { fetch: server.fetch, clock: time.clock, paced: () => true })
    const stop = watch(store)
    await vi.waitFor(() => expect(server.streams).toHaveLength(1))
    server.stored = 15
    store.restart()
    await vi.waitFor(() => expect(store.getSnapshot().head.seq).toBe(15))
    expect(store.getSnapshot().shown.seq).toBeLessThan(15)
    expect(store.getSnapshot().loadedUpTo).toBe(6)
    time.advance(10_000)
    expect(store.getSnapshot().shown.seq).toBe(15)
    stop()
  })
})

describe('the beat between events', () => {
  it('gives a new step the line’s travel and its landing, and a message a short pause', () => {
    expect(MOVE_MS + SMALL_MS).toBe(460)
    const unused: FetchLike = () => Promise.reject(new Error('unused'))
    const base = createLiveRun('run_01JB8', { fetch: unused, clock: handClock().clock, paced: () => true })
    const model = base.getSnapshot().shown
    expect(beatAfter(model, model)).toBe(0)
    expect(beatAfter(model, { ...model, spot: { at: 'planner' } })).toBe(MOVE_MS + SMALL_MS)
    expect(beatAfter(model, { ...model, chat: [...model.chat] })).toBe(SMALL_MS + 100)
  })
})
