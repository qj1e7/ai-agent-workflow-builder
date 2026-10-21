import type { RunClock } from '../api/clock'
import type { Ms, RunId, RunTime, WallTime } from './brand'

export interface Clock {
  /** For pacing beats. Date.now in the browser, which vitest fake timers and Playwright's page.clock drive. */
  wall(): WallTime
  /** Now on the run's timeline: the server's clock live, the mock's replay clock in demo mode. */
  runNow(): RunTime
  /** How much faster runNow moves than the wall right now. 1 everywhere real, the demo's squeeze inside a long wait. */
  rate(): number
  /** Calls fn once after ms of wall time. Returns a cancel. */
  after(ms: Ms, fn: () => void): () => void
  /** Wall epoch ms, for the server clock offset. */
  epochNow(): number
  /** Shift runNow by the server's clock offset, learnt from the first response's Date header. */
  setOffset(ms: number): void
}

/**
 * One clock per run. `runClock` is the ApiProvider's clock: Date.now live, the demo platform's
 * replay clock for that run in demo mode.
 */
export function createClock(runClock: RunClock, runId: RunId): Clock {
  let offset = 0
  return {
    wall: () => Date.now() as WallTime,
    runNow: () => (runClock.now(runId) + offset) as RunTime,
    rate: () => runClock.rate(runId),
    after(ms, fn) {
      const handle = setTimeout(fn, Math.max(0, ms))
      return () => clearTimeout(handle)
    },
    epochNow: () => Date.now(),
    setOffset(ms) {
      offset = ms
    },
  }
}
