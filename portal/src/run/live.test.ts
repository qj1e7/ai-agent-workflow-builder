import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authorizedFetch, createDevSession } from '../api/session'
import type { ApprovalView, MockJiraTicket, RunView } from '../api/types'
import { createDemoPlatform, type DemoPlatformHandle } from '../mock'
import type { FetchLike } from '../stream/feed'
import { runId } from './brand'
import { createClock } from './clock'
import type { Speed } from './director'
import { createLiveView, type LiveView, type LiveViewStore } from './live'
import { fixedClock, RELEASE_CHECK, TEST_REGISTRY } from './testing'
import type { StopCaption, Track } from './track'

const START = Date.parse('2026-11-27T02:00:00Z')
const LIVE_RUN = runId('run_01JB8')
const SECOND = 1000
const ORIGIN = 'http://portal.test'

type Raw = { readonly seq: number; readonly ts: string } & Readonly<Record<string, unknown>>
const RAW: readonly Raw[] = success
const at = (seq: number) => Date.parse(RAW[seq - 1]?.ts ?? '')

let demo: DemoPlatformHandle

beforeEach(() => {
  vi.useFakeTimers({ now: START })
  demo = createDemoPlatform(START)
})

afterEach(() => {
  vi.useRealTimers()
})

const trackOf = (view: LiveView): Track => view.track(RELEASE_CHECK).track
const beatSeq = (view: LiveView): number | null => {
  const key = view.track(RELEASE_CHECK).plan?.key
  return key === undefined ? null : Number(key.split(':')[1])
}
const headline = (view: LiveView) => trackOf(view).headline.is

function gateCaption(view: LiveView): StopCaption | undefined {
  return trackOf(view).stops.find((stop) => stop.key === 'gate')?.caption
}

function waited(view: LiveView): number | null {
  const caption = gateCaption(view)
  return caption?.is === 'waiting' ? caption.elapsedMs : null
}

function spedUp(view: LiveView): boolean {
  const caption = gateCaption(view)
  return caption?.is === 'waiting' && caption.spedUp
}

function fetchAs(user: string): typeof fetch {
  const session = createDevSession(null)
  session.choose(user)
  return authorizedFetch(session, demo.fetch, ORIGIN)
}

function open(id = LIVE_RUN, whenFinished: 'rest' | 'replay' = 'rest', speed: Speed = 1) {
  const store: LiveViewStore = createLiveView({
    runId: id,
    env: { fetch: fetchAs('alice'), clock: createClock(demo.clock, id), registry: TEST_REGISTRY },
    whenFinished,
    speed,
  })
  const seen: LiveView[] = []
  const beatStarts = new Map<number, number>()
  const unsubscribe = store.subscribe(() => {
    const snapshot = store.getSnapshot()
    seen.push(snapshot)
    const seq = beatSeq(snapshot)
    if (seq !== null && !beatStarts.has(seq)) beatStarts.set(seq, Date.now() - START)
  })
  return { store, seen, beatStarts, unsubscribe, view: () => store.getSnapshot() }
}

async function tick(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
}

function burstFetch(backlog: number, upTo: number): FetchLike {
  const encoder = new TextEncoder()
  return (input, init) => {
    if (new Headers(init?.headers).get('Accept') === 'text/event-stream') {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const raw of RAW.filter((event) => event.seq > backlog && event.seq <= upTo)) {
            controller.enqueue(encoder.encode(`id: ${raw.seq}\nevent: activity\ndata: ${JSON.stringify(raw)}\n\n`))
          }
        },
      })
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    }
    const after = Number(new URL(input, 'http://portal.test').searchParams.get('after'))
    return Promise.resolve(new Response(JSON.stringify({ events: RAW.filter((raw) => raw.seq > after && raw.seq <= backlog) }), { status: 200 }))
  }
}

async function openBurst(runNow: number) {
  const store = createLiveView({ runId: LIVE_RUN, env: { fetch: burstFetch(3, 17), clock: fixedClock(runNow), registry: TEST_REGISTRY }, whenFinished: 'rest', speed: 1 })
  const close = store.subscribe(() => undefined)
  while (store.getSnapshot().minutes.length < 3) await tick(10)
  return { view: () => store.getSnapshot(), close }
}

async function api<T>(path: string, user = 'alice', init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await fetchAs(user)(`/api/v1${path}`, { ...init, headers })
  return (await response.json()) as T
}

describe('createLiveView against the demo platform', () => {
  it('follows the live run through the agents, the pause with a rising counter, the approval and the write', async () => {
    const { seen, view, unsubscribe } = open()
    await tick(0)
    expect(view().connection.is).toBe('live')
    expect(headline(view())).toBe('starting')
    expect(trackOf(view()).stops[0]?.cast.map((figure) => figure.key)).toEqual(['person:alice'])

    await tick(18 * SECOND)
    expect(headline(view())).toBe('waiting')
    const firstWait = waited(view()) ?? Number.NaN
    await tick(4 * SECOND)
    expect(headline(view())).toBe('waiting')
    expect(waited(view())).toBeGreaterThan(firstWait)
    expect(view().atHead).toBe(true)

    const headlines = new Set(seen.map(headline))
    expect([...headlines]).toEqual(expect.arrayContaining(['starting', 'working', 'found', 'drafting', 'waiting']))
    const beats = seen.flatMap((snapshot) => beatSeq(snapshot) ?? [])
    expect([...new Set(beats)]).toEqual([4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17])

    await tick(11 * SECOND)
    expect(trackOf(view()).gate?.state).toBe('open')
    await tick(60 * SECOND)
    expect(trackOf(view()).headline).toEqual({ is: 'written', lines: [{ reference: 'MOCK-142', connector: 'jira' }] })
    expect(view().atHead).toBe(true)
    expect(view().connection.is).toBe('settled')
    unsubscribe()
  })

  it('plays the paced demo on time: the chips land by 10.5 s, the pause by 18 s, the decision at 32.6 s and Done under 40 s', async () => {
    const { beatStarts, unsubscribe } = open()
    await tick(45 * SECOND)
    expect([...beatStarts]).toEqual([
      [4, 1470],
      [5, 2470],
      [6, 5345],
      [7, 6345],
      [8, 7945],
      [9, 8845],
      [10, 10445],
      [11, 13770],
      [12, 16345],
      [15, 17745],
      [17, 19345],
      [18, 32566],
      [21, 34366],
      [23, 36566],
    ])
    const findingBeat = beatStarts.get(9) ?? Number.NaN
    expect(findingBeat + 1600 - 250, 'the chips are at rest 250 ms before the finding beat ends').toBeLessThanOrEqual(10_500)
    expect(beatStarts.get(15), 'the pause').toBeLessThanOrEqual(18_000)
    expect(beatStarts.get(23), 'Done').toBeLessThan(40_000)
    unsubscribe()
  })

  it("counts the live wait as the head's wait, not the shown frame's, while the view catches up on an open approval", async () => {
    const now = at(17) + 90 * SECOND
    const { view, close } = await openBurst(now)
    while (headline(view()) !== 'waiting') await tick(100)
    expect(view().atHead, 'the view is still catching up').toBe(false)
    expect(waited(view())).toBe(now - at(15))
    close()
  })

  it("counts the shown frame's own wait in replay, and says Sped up through the replay's compressed wait", async () => {
    const { view, unsubscribe } = open()
    await tick(80 * SECOND)
    expect(view().atHead).toBe(true)

    view().controls.restart()
    while (headline(view()) !== 'waiting') await tick(100)
    expect(view().atHead).toBe(false)
    expect(spedUp(view())).toBe(false)
    expect(waited(view())).toBeLessThan(60 * SECOND)

    while (!spedUp(view())) await tick(100)
    expect(headline(view())).toBe('waiting')
    unsubscribe()
  })

  it('says Sped up while the demo squeezes the wait for Bob', async () => {
    const { view, unsubscribe } = open()
    await tick(20 * SECOND)
    expect(headline(view())).toBe('waiting')
    expect(spedUp(view()), 'the head of the wait plays at real speed').toBe(false)
    await tick(6 * SECOND)
    expect(spedUp(view())).toBe(true)
    expect(waited(view())).toBeGreaterThan(60 * SECOND)
    await tick(8 * SECOND)
    expect(trackOf(view()).gate?.state).toBe('open')
    expect(spedUp(view())).toBe(false)
    unsubscribe()
  })

  it('ends each recorded run at its outcome, and is not at the head while catching up', async () => {
    const behind = await openBurst(at(17) + SECOND)
    expect(behind.view().atHead).toBe(false)
    behind.close()

    const live = open()
    await tick(88 * SECOND)
    expect(headline(live.view())).toBe('written')
    expect(live.view().atHead).toBe(true)
    live.unsubscribe()

    const failed = open(runId('run_01JB9'))
    await tick(0)
    expect(headline(failed.view())).toBe('stopped')
    expect(trackOf(failed.view()).panel).toMatchObject({ is: 'trouble', retryable: true })
    failed.unsubscribe()

    const rejected = open(runId('run_01JBA'))
    await tick(0)
    expect(trackOf(rejected.view()).headline).toEqual({ is: 'declined', by: 'Bob' })
    rejected.unsubscribe()
  })

  it('shows a real decision by Bob and the ticket it writes', async () => {
    const { view, unsubscribe } = open()
    await tick(18 * SECOND)
    const run = await api<RunView>(`/runs/${LIVE_RUN}`)
    if (run.state !== 'awaiting_approval') throw new Error(`run is ${run.state}`)
    const approval = await api<ApprovalView>(`/approvals/${run.approval.approval_id}`, 'bob')
    expect(approval.you_can_decide).toBe(true)
    await api(`/approvals/${run.approval.approval_id}/decisions`, 'bob', {
      method: 'POST',
      body: JSON.stringify({ step: 0, verdict: 'approve', digest: approval.digest }),
    })
    await tick(15 * SECOND)
    const panel = trackOf(view()).panel
    const written = panel?.is === 'written' ? panel.lines[0]?.reference : undefined
    expect(written).toMatch(/^MOCK-\d+$/)
    const tickets = await api<{ tickets: MockJiraTicket[] }>('/mock-jira/tickets')
    expect(tickets.tickets.map((ticket) => ticket.key)).toContain(written)
    expect(panel).toMatchObject({ approvedBy: ['Bob'] })
    unsubscribe()
  })

  it('rests on a finished run, or replays it once from the start when asked', async () => {
    const rest = open(runId('run_01JB9'), 'rest')
    await tick(0)
    expect(headline(rest.view())).toBe('stopped')
    expect(rest.view().atHead).toBe(true)
    expect(rest.view().track(RELEASE_CHECK).plan).toBeNull()
    rest.unsubscribe()

    const replay = open(runId('run_01JB9'), 'replay')
    await tick(0)
    expect(replay.view().atHead).toBe(false)
    expect(replay.view().track(RELEASE_CHECK).plan).toMatchObject({ key: '1:1', entry: 'continuous' })
    expect(headline(replay.view())).toBe('starting')
    await tick(40 * SECOND)
    expect(replay.view().atHead).toBe(true)
    expect(headline(replay.view())).toBe('stopped')
    expect(trackOf(replay.view()).stops[1]?.cast.find((figure) => figure.is === 'agent' && figure.status === 'stopped')).toBeDefined()
    replay.unsubscribe()
  })

  it('starts at the speed it is given, and Instant lands on the newest frame at once', async () => {
    const instant = open(LIVE_RUN, 'rest', 'instant')
    await tick(3 * SECOND)
    expect(instant.view().speed).toBe('instant')
    expect(instant.view().atHead).toBe(true)
    expect(instant.view().track(RELEASE_CHECK).plan).toBeNull()
    instant.unsubscribe()

    const live = open()
    await tick(3 * SECOND)
    expect(live.view().track(RELEASE_CHECK).plan).not.toBeNull()
    live.view().controls.setSpeed('instant')
    expect(live.view().speed).toBe('instant')
    expect(live.view().atHead).toBe(true)
    expect(live.view().track(RELEASE_CHECK).plan).toBeNull()
    live.view().controls.setSpeed(2)
    expect(live.view().speed).toBe(2)
    live.unsubscribe()
  })

  it('gives the same track for the same blocks in one snapshot, and a fresh one for other blocks', async () => {
    const { view, unsubscribe } = open()
    await tick(2 * SECOND)
    const snapshot = view()
    expect(snapshot.track(RELEASE_CHECK)).toBe(snapshot.track(RELEASE_CHECK))
    const other = snapshot.track([...RELEASE_CHECK])
    expect(other).not.toBe(snapshot.track(RELEASE_CHECK))
    expect(other).toEqual(snapshot.track(RELEASE_CHECK))
    unsubscribe()
  })

  it('retries a failed run: attempt 2 starts with no stopped agent', async () => {
    const { view, unsubscribe } = open(runId('run_01JB9'))
    await tick(0)
    expect(headline(view())).toBe('stopped')
    const retry = await fetchAs('alice')(`/api/v1/runs/run_01JB9/retry`, { method: 'POST' })
    expect(retry.status).toBe(202)
    view().controls.reconnect()
    await tick(5 * SECOND)
    expect(trackOf(view()).attempt).toBe(2)
    expect(trackOf(view()).breakAt).toBeNull()
    expect(['working', 'found', 'drafting', 'waiting']).toContain(headline(view()))
    unsubscribe()
  })

  it('survives StrictMode: subscribe, unsubscribe, subscribe keeps one tape and repeats nothing', async () => {
    const { store, unsubscribe } = open()
    await tick(2 * SECOND)
    const shown = store.getSnapshot().minutes.length
    unsubscribe()
    const again = store.subscribe(() => undefined)
    await tick(0)
    expect(store.getSnapshot().minutes.length).toBeGreaterThanOrEqual(shown)
    const seqs = store.getSnapshot().minutes.map((entry) => entry.seq)
    expect(seqs).toEqual([...new Set(seqs)])
    again()
  })
})

describe('reconnect after a retry', () => {
  /** A platform whose stream has closed: only pages answer, and the SSE request never does. */
  function pagesOnly(events: () => readonly Raw[]): FetchLike {
    return (input, init) => {
      if (new Headers(init?.headers).get('Accept') === 'text/event-stream') {
        return new Promise((_, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
      }
      const after = Number(new URL(input, 'http://portal.test').searchParams.get('after'))
      return Promise.resolve(new Response(JSON.stringify({ events: events().filter((raw) => raw.seq > after) }), { status: 200 }))
    }
  }

  it('plays the events a reconnect brings back as live, so the retry animates instead of jumping', async () => {
    const recorded: readonly Raw[] = failure
    let events = recorded
    const store = createLiveView({
      runId: runId('run_01JB9'),
      env: { fetch: pagesOnly(() => events), clock: fixedClock(Date.parse('2026-11-04T02:20:00Z')), registry: TEST_REGISTRY },
      whenFinished: 'rest',
      speed: 1,
    })
    const beats: number[] = []
    const close = store.subscribe(() => {
      const seq = beatSeq(store.getSnapshot())
      if (seq !== null && !beats.includes(seq)) beats.push(seq)
    })
    await tick(0)
    expect(headline(store.getSnapshot())).toBe('stopped')
    expect(beats, 'the first backlog rests on the end').toEqual([])

    events = [
      ...recorded,
      { seq: 13, run_id: 'run_01JB9', ts: '2026-11-04T02:20:00Z', actor: { kind: 'user', id: 'alice', display: 'Alice' }, summary: 'Alice retried the run.', kind: 'run_retried', data: { leg: 'work', attempt: 2 } },
    ]
    store.getSnapshot().controls.reconnect()
    await tick(0)
    expect(beats).toEqual([13])
    expect(trackOf(store.getSnapshot()).attempt).toBe(2)
    close()
  })
})
