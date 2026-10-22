import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createOidcSession } from '../api/oidc'
import { authorizedFetch, SIGNED_IN } from '../api/session'
import { fakeOidcClient, fakeUser } from '../api/testing'
import { runId } from '../run/brand'
import { runFeed, type FeedClock, type FeedItem } from './feed'

const NOW = Date.parse('2026-11-27T02:00:00Z')
const ORIGIN = 'http://portal.test'
const RUN = runId('run_01JB8')

interface Seen {
  readonly accept: string | null
  readonly authorization: string | null
}

/** A platform that records each request's Accept and Authorization headers. Its streams stay open until closed. */
function platform() {
  const seen: Seen[] = []
  const streams: ReadableStreamDefaultController<Uint8Array>[] = []
  const fetchImpl: typeof fetch = (input, init) => {
    const request = new Request(input, init)
    seen.push({ accept: request.headers.get('Accept'), authorization: request.headers.get('Authorization') })
    if (request.headers.get('Accept') === 'text/event-stream') {
      const body = new ReadableStream<Uint8Array>({ start: (controller) => void streams.push(controller) })
      return Promise.resolve(new Response(body, { status: 200 }))
    }
    return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }))
  }
  return { seen, streams, fetchImpl }
}

async function next(feed: AsyncGenerator<FeedItem>): Promise<FeedItem> {
  const result = await feed.next()
  if (result.done) throw new Error('the feed finished early')
  return result.value
}

const clock: FeedClock = {
  after: (ms, fn) => {
    const timer = setTimeout(fn, ms)
    return () => clearTimeout(timer)
  },
  epochNow: () => Date.now(),
}

beforeEach(() => vi.useFakeTimers({ now: NOW }))
afterEach(() => vi.useRealTimers())

describe('runFeed over authorizedFetch', () => {
  it('sends the bearer on the page, on the stream, and the renewed one on a reconnect', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, Date.now)
    const { seen, streams, fetchImpl } = platform()
    const feed = runFeed({ runId: RUN, fetch: authorizedFetch(session, fetchImpl, ORIGIN), clock, after: 0, signal: new AbortController().signal, random: () => 0 })
    const items: FeedItem[] = []
    const pull = async () => {
      items.push(await next(feed))
    }
    await pull()
    await pull()
    expect(items.map((item) => item.type === 'connection' && item.connection.is)).toEqual(['connecting', 'live'])
    expect(seen).toEqual([
      { accept: 'application/json', authorization: 'Bearer token-1' },
      { accept: 'text/event-stream', authorization: 'Bearer token-1' },
    ])

    client.fire.userLoaded(fakeUser('token-2', NOW))
    streams[0]?.close()
    await pull()
    expect(items.at(-1)).toMatchObject({ connection: { is: 'reconnecting' } })
    const back = pull()
    await vi.advanceTimersByTimeAsync(500)
    await back
    expect(items.at(-1)).toEqual({ type: 'connection', connection: { is: 'live' } })
    expect(seen.slice(2)).toEqual([
      { accept: 'application/json', authorization: 'Bearer token-2' },
      { accept: 'text/event-stream', authorization: 'Bearer token-2' },
    ])
  })

  it('closes as signed out, without a request, once the session has expired', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, Date.now)
    client.fire.silentRenewError()
    const { seen, fetchImpl } = platform()
    const feed = runFeed({ runId: RUN, fetch: authorizedFetch(session, fetchImpl, ORIGIN), clock, after: 0, signal: new AbortController().signal })
    await next(feed)
    expect(await next(feed)).toEqual({ type: 'connection', connection: { is: 'closed', status: 401, reason: 'signed_out' } })
    expect(seen).toEqual([])
  })
})
