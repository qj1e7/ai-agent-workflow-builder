import success from '@contracts/fixtures/runs/success.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FetchLike } from '../stream/feed'
import { runId } from './brand'
import { createLiveView, type LiveView } from './live'
import { fixedClock, TEST_REGISTRY } from './testing'

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

async function open(events: readonly Raw[], runNow: number): Promise<{ view(this: void): LiveView; close(this: void): void }> {
  const store = createLiveView({ runId: RUN, env: { fetch: scriptedFetch(events), clock: fixedClock(runNow), registry: TEST_REGISTRY }, whenFinished: 'rest' })
  const close = store.subscribe(() => undefined)
  await vi.advanceTimersByTimeAsync(0)
  return { view: () => store.getSnapshot(), close }
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
    }
    close()
  })

  it('keeps the live waiting counter honest while the run waits for an Approver', async () => {
    const now = at(17) + 90_000
    const { view, close } = await open(skewed(17), now)
    expect(view().room.phase.name).toBe('awaiting_approval')
    expect(view().frame.waiting).toEqual({ since: at(15), elapsedMs: now - at(15) })
    expect(view().frame.elapsed.at).toBeGreaterThanOrEqual(0)
    expect(view().frame.elapsed.at).toBeLessThanOrEqual(view().frame.elapsed.total)
    close()
  })
})
