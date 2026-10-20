import success from '@contracts/fixtures/runs/success.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FetchLike } from '../stream/feed'
import { runId, runTime, wallTime } from './brand'
import type { Clock } from './clock'
import { createLiveView, type LiveView } from './live'
import { layoutScrubber, SCRUB } from './scrubber'
import { TEST_REGISTRY } from './testing'

/**
 * The fake agent stamps its events with the recording's times while the platform stamps its own with
 * today's, so inside one run the clock jumps 320 h forward at seq 4 and back again at seq 12. Clock skew
 * between the agent runtime and the platform does a milder version of the same with the real agent.
 */
const SKEW_MS = 320 * 3_600_000
const RUN = runId('run_01JB8')

interface Raw {
  readonly seq: number
  readonly ts: string
  readonly actor: { readonly kind: string }
}

function skewed(upTo: number): Raw[] {
  return (success as Raw[])
    .filter((raw) => raw.seq <= upTo)
    .map((raw) => (raw.actor.kind === 'agent' ? { ...raw, ts: new Date(Date.parse(raw.ts) + SKEW_MS).toISOString() } : raw))
}

const at = (seq: number) => Date.parse((success as Raw[])[seq - 1]?.ts ?? '')

function scriptedFetch(events: readonly Raw[]): FetchLike {
  return (input, init) => {
    if (new Headers(init?.headers).get('Accept') === 'text/event-stream') {
      return new Promise((_, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    }
    const after = Number(new URL(input, 'http://portal.test').searchParams.get('after'))
    return Promise.resolve(new Response(JSON.stringify({ events: events.filter((raw) => raw.seq > after) }), { status: 200 }))
  }
}

function clockAt(runNow: number): Clock {
  return {
    wall: () => wallTime(Date.now()),
    runNow: () => runTime(runNow),
    after(ms, fn) {
      const handle = setTimeout(fn, ms)
      return () => clearTimeout(handle)
    },
    epochNow: () => Date.now(),
    setOffset: () => undefined,
  }
}

async function open(events: readonly Raw[], runNow: number): Promise<{ view(this: void): LiveView; close(this: void): void }> {
  const store = createLiveView({ runId: RUN, env: { fetch: scriptedFetch(events), clock: clockAt(runNow), registry: TEST_REGISTRY }, whenFinished: 'rest' })
  const close = store.subscribe(() => undefined)
  await vi.advanceTimersByTimeAsync(0)
  return { view: () => store.getSnapshot(), close }
}

function expectSaneTrack(view: LiveView, width: number): void {
  const track = view.track(width)
  for (const wait of track.waits) {
    expect(wait.w, 'wait width').toBeGreaterThanOrEqual(0)
    expect(wait.fill, 'wait fill').toBeGreaterThanOrEqual(0)
    expect(wait.fill, 'wait fill within width').toBeLessThanOrEqual(wait.w)
    expect(wait.lasted, 'wait lasted').toBeGreaterThanOrEqual(0)
    expect(Number.isFinite(wait.x) && Number.isFinite(wait.lasted), 'finite wait').toBe(true)
  }
  for (let cursor = 1; cursor <= view.frame.head; cursor += 1) {
    expect(track.xOf(cursor), `x of ${cursor} never steps back`).toBeGreaterThanOrEqual(track.xOf(cursor - 1))
    expect(Number.isFinite(track.xOf(cursor))).toBe(true)
  }
}

beforeEach(() => vi.useFakeTimers({ now: Date.parse('2026-11-03T02:14:00Z') }))
afterEach(() => vi.useRealTimers())

describe('a run whose event times jump forward and back', () => {
  it('keeps elapsed time between zero and the total at every frame of the finished run', async () => {
    const { view, close } = await open(skewed(23), at(23))
    expect(view().transport.settled).toBe(true)
    for (let cursor = 0; cursor <= 23; cursor += 1) {
      view().transport.seek(cursor)
      const { at: shown, total } = view().frame.elapsed
      expect(Number.isFinite(shown) && Number.isFinite(total), `finite at frame ${cursor}`).toBe(true)
      expect(shown, `elapsed at frame ${cursor}`).toBeGreaterThanOrEqual(0)
      expect(shown, `elapsed within total at frame ${cursor}`).toBeLessThanOrEqual(total)
      expectSaneTrack(view(), 600)
    }
    close()
  })

  it('draws a gap that goes backwards like a tiny gap, never as a wait', async () => {
    const { view, close } = await open(skewed(23), at(23))
    const marks = view().transport.marks
    const track = layoutScrubber({ marks, width: 600, edge: null })
    const back = marks.findIndex((mark, i) => i > 0 && mark.at < (marks[i - 1]?.at ?? 0))
    expect(back, 'the skew makes one gap go backwards').toBeGreaterThan(0)
    const backwards = track.xOf(back + 1) - track.xOf(back)
    const tiny = track.xOf(9) - track.xOf(8)
    expect(at(9) - at(8)).toBeLessThan(SCRUB.minTickMs)
    expect(backwards).toBeGreaterThan(0)
    expect(Math.abs(backwards - tiny)).toBeLessThanOrEqual(1)
    expect(track.waits.some((wait) => wait.x === track.xOf(back))).toBe(false)
    close()
  })

  it('keeps the live waiting counter honest while the run waits for an Approver', async () => {
    const now = at(17) + 90_000
    const { view, close } = await open(skewed(17), now)
    expect(view().room.phase.name).toBe('awaiting_approval')
    expect(view().frame.waiting).toEqual({ since: at(15), elapsedMs: now - at(15) })
    expect(view().frame.elapsed.at).toBeGreaterThanOrEqual(0)
    expect(view().frame.elapsed.at).toBeLessThanOrEqual(view().frame.elapsed.total)
    expectSaneTrack(view(), 600)
    close()
  })
})
