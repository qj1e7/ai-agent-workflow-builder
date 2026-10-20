import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApprovalView, MockJiraTicket, RunView } from '../api/types'
import { createDemoPlatform, type DemoPlatformHandle } from '../mock'
import { runId } from './brand'
import { createClock } from './clock'
import { createLiveView, type LiveView, type LiveViewStore } from './live'
import { TEST_REGISTRY } from './testing'

const START = Date.parse('2026-11-27T02:00:00Z')
const LIVE_RUN = runId('run_01JB8')
const SECOND = 1000

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
  const unsubscribe = store.subscribe(() => seen.push(store.getSnapshot()))
  return { store, seen, unsubscribe, view: () => store.getSnapshot() }
}

async function tick(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
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

    // Each message holds for its reading time, so the pause lands after 17 s of live play, and the demo's
    // squeezed wait brings Bob's decision at about 20.7 s: the honest counter rises between the two.
    await tick(18 * SECOND)
    expect(view().room.phase.name).toBe('awaiting_approval')
    expect(view().frame.waiting).not.toBeNull()
    const firstWait = view().frame.waiting?.elapsedMs ?? 0
    await tick(2 * SECOND)
    const laterWait = view().frame.waiting?.elapsedMs ?? 0
    expect(laterWait).toBeGreaterThan(firstWait)
    expect(view().frame.label).toBe('live')
    expect(view().transport.atEdge).toBe(true)
    expect(view().room.doors.find((door) => door.side === 'write')).toMatchObject({ key: 'jira', checker: 'locked' })

    const phases = new Set(seen.map((snapshot) => snapshot.room.phase.name))
    expect([...phases]).toEqual(expect.arrayContaining(['pending', 'working', 'proposed', 'awaiting_approval']))
    const beats = seen.flatMap((snapshot) => (snapshot.frame.beat?.type === 'event' ? [snapshot.frame.beat.seq] : []))
    expect([...new Set(beats)]).toEqual([4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17])

    await tick(60 * SECOND)
    expect(view().room.phase).toEqual({ name: 'succeeded', outcome: 'written' })
    expect(view().room.ticket?.lines[0]?.reference).toBe('MOCK-142')
    expect(view().frame.label).toBe('finished')
    expect(view().connection.is).toBe('settled')
    expect(view().transport.settled).toBe(true)
    unsubscribe()
  })

  it('shows a real decision by Bob and the ticket it writes', async () => {
    const { view, unsubscribe } = open()
    await tick(14 * SECOND)
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
