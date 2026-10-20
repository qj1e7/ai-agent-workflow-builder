import success from '@contracts/fixtures/runs/success.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApprovalView, MockJiraTicket, RunView } from '../api/types'
import { createDemoPlatform, type DemoPlatformHandle } from '../mock'
import type { FetchLike } from '../stream/feed'
import { formatDuration } from '../ui/format'
import { runId } from './brand'
import { createClock } from './clock'
import { createLiveView, type LiveView, type LiveViewStore } from './live'
import { statusOf } from './status'
import { fixedClock, TEST_REGISTRY } from './testing'

const START = Date.parse('2026-11-27T02:00:00Z')
const LIVE_RUN = runId('run_01JB8')
const SECOND = 1000

interface Raw {
  readonly seq: number
  readonly ts: string
}
const RAW = success as Raw[]
const at = (seq: number) => Date.parse(RAW[seq - 1]?.ts ?? '')

let demo: DemoPlatformHandle

beforeEach(() => {
  vi.useFakeTimers({ now: START })
  demo = createDemoPlatform(START)
})

afterEach(() => {
  vi.useRealTimers()
})

function open(id = LIVE_RUN, whenFinished: 'rest' | 'replay' = 'rest', openingMs = 0) {
  const authed: typeof fetch = (input, init) => {
    const headers = new Headers(init?.headers)
    if (!headers.has('X-Dev-User')) headers.set('X-Dev-User', 'alice')
    return demo.fetch(input, { ...init, headers })
  }
  const store: LiveViewStore = createLiveView({
    runId: id,
    env: { fetch: authed, clock: createClock(demo.now, id), registry: TEST_REGISTRY },
    whenFinished,
    openingMs,
  })
  const seen: LiveView[] = []
  const beatStarts = new Map<number, number>()
  const unsubscribe = store.subscribe(() => {
    const snapshot = store.getSnapshot()
    seen.push(snapshot)
    const beat = snapshot.frame.beat
    if (beat?.type === 'event' && !beatStarts.has(beat.seq)) beatStarts.set(beat.seq, Date.now() - START)
  })
  return { store, seen, beatStarts, unsubscribe, view: () => store.getSnapshot() }
}

async function tick(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
}

/** A page holding events 1..backlog, then every event up to upTo on the stream at once: a room that must catch up. */
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
  const store = createLiveView({ runId: LIVE_RUN, env: { fetch: burstFetch(3, 17), clock: fixedClock(runNow), registry: TEST_REGISTRY }, whenFinished: 'rest' })
  const close = store.subscribe(() => undefined)
  while (store.getSnapshot().frame.head < 17) await tick(10)
  return { view: () => store.getSnapshot(), close }
}

async function api<T>(path: string, user = 'alice', init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-Dev-User', user)
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await demo.fetch(`/api/v1${path}`, { ...init, headers })
  return (await response.json()) as T
}

describe('createLiveView against the demo platform', () => {
  it('follows the live run through the agents, the pause with a rising counter, the approval and the write', async () => {
    const { seen, view, unsubscribe } = open()
    await tick(0)
    expect(view().connection.is).toBe('live')
    expect(view().room.phase.name).toBe('pending')
    expect(view().room.agents.map((seat) => seat.id)).toEqual(['room_lead'])

    // The demo is paced so the room never catches up (the schedule in src/mock/timeline.test.ts): the pause
    // lands at 17.3 s and Bob's recorded decision at 32.2 s, and the honest counter rises between the two.
    await tick(18 * SECOND)
    expect(view().room.phase.name).toBe('awaiting_approval')
    expect(view().frame.waiting).not.toBeNull()
    const firstWait = view().frame.waiting?.elapsedMs ?? 0
    await tick(4 * SECOND)
    expect(view().room.phase.name).toBe('awaiting_approval')
    const laterWait = view().frame.waiting?.elapsedMs ?? 0
    expect(laterWait).toBeGreaterThan(firstWait)
    expect(view().frame.label).toBe('live')
    expect(view().transport.atEdge).toBe(true)
    expect(view().frame.elapsed.at, 'live, the transport shows one clock: the run is as long as it has run').toBe(view().frame.elapsed.total)
    expect(view().room.doors.find((door) => door.side === 'write')).toMatchObject({ key: 'jira', checker: 'locked' })

    const phases = new Set(seen.map((snapshot) => snapshot.room.phase.name))
    expect([...phases]).toEqual(expect.arrayContaining(['pending', 'working', 'proposed', 'awaiting_approval']))
    const beats = seen.flatMap((snapshot) => (snapshot.frame.beat?.type === 'event' ? [snapshot.frame.beat.seq] : []))
    expect([...new Set(beats)]).toEqual([4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17])

    await tick(11 * SECOND)
    expect(view().room.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob', display: 'Bob' } })
    await tick(60 * SECOND)
    expect(view().room.phase).toEqual({ name: 'succeeded', outcome: 'written' })
    expect(view().room.ticket?.lines[0]?.reference).toBe('MOCK-142')
    expect(view().frame.label).toBe('finished')
    expect(view().connection.is).toBe('settled')
    expect(view().transport.settled).toBe(true)
    unsubscribe()
  })

  it('plays the paced demo on time: the chips land by 10.5 s, the pause by 18 s, the decision at 32 s and Done under 40 s', async () => {
    const { beatStarts, unsubscribe } = open()
    await tick(45 * SECOND)
    // Measured with the store under fake timers. Each story beat starts when its event lands, since the
    // demo never queues more than one beat; the wall offsets are the schedule in src/mock/timeline.test.ts.
    expect([...beatStarts]).toEqual([
      [4, 1470],
      [5, 2470],
      [6, 5345],
      [7, 6345],
      [8, 7745],
      [9, 8645],
      [10, 10045],
      [11, 13370],
      [12, 15945],
      [15, 17345],
      [17, 18945],
      [18, 32166],
      [21, 33966],
      [23, 36166],
    ])
    const findingBeat = beatStarts.get(9) ?? Number.NaN
    expect(findingBeat + 1400 - 250, 'the chips are at rest 250 ms before the finding beat ends').toBeLessThanOrEqual(10_500)
    expect(beatStarts.get(15), 'the pause').toBeLessThanOrEqual(18_000)
    expect(beatStarts.get(23), 'Done').toBeLessThan(40_000)
    unsubscribe()
  })

  it("counts the live wait as the edge's wait, not the shown frame's, while the room catches up on an open approval", async () => {
    const now = at(17) + 90 * SECOND
    const { view, close } = await openBurst(now)
    while (view().room.phase.name !== 'awaiting_approval') await tick(100)
    expect(view().frame.shown, 'the room is still catching up').toBeLessThan(view().frame.head)
    const edge = view().transport.edge
    if (!edge?.waitingSince) throw new Error('no live edge')
    const liveWait = view().frame.waiting?.elapsedMs ?? 0
    expect(liveWait).toBe(edge.now - edge.waitingSince)
    expect(liveWait).toBe(now - at(15))
    const shown = view().frame
    expect(liveWait, "the live wait, not the shown frame's own").toBeGreaterThan(shown.sceneTime - (shown.waiting?.since ?? 0))
    expect(view().describe()).toContain(`for ${formatDuration(liveWait)}.`)
    close()
  })

  it("counts the shown frame's own wait in replay and after a seek, and says Sped up through the replay's compressed wait", async () => {
    const { view, unsubscribe } = open()
    await tick(80 * SECOND)
    expect(view().transport.settled).toBe(true)
    view().transport.seek(15)
    expect(view().frame.mode).toBe('replay')
    const sought = view().frame
    expect(sought.waiting?.elapsedMs).toBe(sought.sceneTime - (sought.waiting?.since ?? 0))
    expect(sought.waiting?.elapsedMs).toBeLessThan(60 * SECOND)
    expect(sought.elapsed.at, 'behind the end, the transport shows the position of the total').toBeLessThan(sought.elapsed.total)
    expect(statusOf(view())).toBe('replay')

    view().transport.restart()
    while (view().room.phase.name !== 'awaiting_approval') await tick(100)
    const replayed = view().frame
    expect(replayed.mode).toBe('replay')
    expect(replayed.spedUp).toBe(false)
    expect(replayed.waiting?.elapsedMs).toBe(replayed.sceneTime - (replayed.waiting?.since ?? 0))
    expect(replayed.waiting?.elapsedMs).toBeLessThan(60 * SECOND)
    expect(view().describe()).toContain(`for ${formatDuration(replayed.waiting?.elapsedMs ?? 0)}.`)

    while (view().frame.beat?.type !== 'hold') await tick(100)
    expect(view().frame.spedUp).toBe(true)
    expect(statusOf(view())).toBe('sped_up')
    unsubscribe()
  })

  it("says Sped up while the demo squeezes the wait for Bob, on the transport and in the frame the seat reads", async () => {
    const { view, unsubscribe } = open()
    await tick(20 * SECOND)
    expect(view().room.phase.name).toBe('awaiting_approval')
    expect(view().frame.spedUp, 'the head of the wait plays at real speed').toBe(false)
    expect(statusOf(view())).toBe('live')
    await tick(6 * SECOND)
    expect(view().frame.spedUp).toBe(true)
    expect(statusOf(view())).toBe('sped_up')
    expect(view().frame.waiting?.elapsedMs ?? 0).toBeGreaterThan(60 * SECOND)
    await tick(8 * SECOND)
    expect(view().room.approval?.steps[0]?.state.is).toBe('approved')
    expect(view().frame.spedUp).toBe(false)
    unsubscribe()
  })

  it('says the outcome on the transport: Done, Declined, Stopped, and Catching up while behind the live edge', async () => {
    const behind = await openBurst(at(17) + SECOND)
    expect(behind.view().frame.shown).toBeLessThan(behind.view().frame.head)
    expect(statusOf(behind.view())).toBe('catching_up')
    behind.close()

    const live = open()
    await tick(0)
    expect(statusOf(live.view())).toBe('live')
    await tick(8 * SECOND)
    expect(statusOf(live.view()), 'the paced demo never has to catch up').toBe('live')
    await tick(80 * SECOND)
    expect(live.view().room.phase.name).toBe('succeeded')
    expect(statusOf(live.view())).toBe('done')
    live.view().transport.seek(5)
    expect(statusOf(live.view())).toBe('replay')
    live.unsubscribe()

    const failed = open(runId('run_01JB9'))
    await tick(0)
    expect(failed.view().room.phase.name).toBe('failed')
    expect(statusOf(failed.view())).toBe('stopped')
    failed.unsubscribe()

    const rejected = open(runId('run_01JBA'))
    await tick(0)
    expect(rejected.view().room.phase.name).toBe('rejected')
    expect(statusOf(rejected.view())).toBe('declined')
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
    const written = view().room.ticket?.lines[0]?.reference
    expect(written).toMatch(/^MOCK-\d+$/)
    const tickets = await api<{ tickets: MockJiraTicket[] }>('/mock-jira/tickets')
    expect(tickets.tickets.map((ticket) => ticket.key)).toContain(written)
    expect(view().room.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob', display: 'Bob' } })
    unsubscribe()
  })

  it('rests on a finished run, or replays it once from the start when asked', async () => {
    const rest = open(runId('run_01JB9'), 'rest')
    await tick(0)
    expect(rest.view().room.phase.name).toBe('failed')
    expect(rest.view().frame.label).toBe('finished')
    expect(rest.view().frame.beat).toBeNull()
    rest.unsubscribe()

    const replay = open(runId('run_01JB9'), 'replay')
    await tick(0)
    expect(replay.view().frame.mode).toBe('replay')
    expect(replay.view().frame.shown).toBe(1)
    expect(replay.view().frame.beat).toMatchObject({ type: 'event', seq: 1, entry: 'continuous' })
    await tick(40 * SECOND)
    expect(replay.view().frame.label).toBe('finished')
    expect(replay.view().room.phase.name).toBe('failed')
    expect(replay.view().room.agents.map((seat) => seat.id)).toContain('troubleshooter')
    replay.unsubscribe()
  })

  it('holds the first beat for the opening: a replay restarts only when the hold ends', async () => {
    const { view, unsubscribe } = open(runId('run_01JB9'), 'replay', 900)
    await tick(0)
    expect(view().frame.shown).toBe(view().frame.head)
    expect(view().frame.beat).toBeNull()
    await tick(899)
    expect(view().frame.beat).toBeNull()
    await tick(2)
    expect(view().frame.mode).toBe('replay')
    expect(view().frame.shown).toBe(1)
    expect(view().frame.beat).toMatchObject({ type: 'event', seq: 1 })
    unsubscribe()
  })

  it('holds the first beat for the opening: a live event that lands during the hold plays after it', async () => {
    const { view, unsubscribe } = open(LIVE_RUN, 'rest', 3000)
    await tick(2900)
    expect(view().frame.head).toBeGreaterThanOrEqual(4)
    expect(view().room.phase.name).toBe('pending')
    expect(view().frame.beat).toBeNull()
    await tick(200)
    expect(view().frame.beat).toMatchObject({ type: 'event', seq: 4 })
    expect(view().room.agents.map((seat) => seat.id)).toContain('release_checker')
    unsubscribe()
  })

  it('retries a failed run: the troubleshooter leaves and the agents start again', async () => {
    const { view, unsubscribe } = open(runId('run_01JB9'))
    await tick(0)
    expect(view().room.phase.name).toBe('failed')
    const retry = await demo.fetch(`/api/v1/runs/run_01JB9/retry`, { method: 'POST', headers: { 'X-Dev-User': 'alice' } })
    expect(retry.status).toBe(202)
    view().transport.reconnect()
    await tick(5 * SECOND)
    expect(view().room.attempt).toBe(2)
    expect(view().room.agents.map((seat) => seat.id)).not.toContain('troubleshooter')
    expect(['working', 'proposed', 'awaiting_approval']).toContain(view().room.phase.name)
    unsubscribe()
  })

  it('survives StrictMode: subscribe, unsubscribe, subscribe keeps one tape and repeats nothing', async () => {
    const { store, unsubscribe } = open()
    await tick(2 * SECOND)
    const head = store.getSnapshot().frame.head
    unsubscribe()
    const again = store.subscribe(() => undefined)
    await tick(0)
    expect(store.getSnapshot().frame.head).toBeGreaterThanOrEqual(head)
    const seqs = store.getSnapshot().minutes.map((entry) => entry.seq)
    expect(seqs).toEqual([...new Set(seqs)])
    again()
  })
})
