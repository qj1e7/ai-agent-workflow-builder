export interface RunClock {
  now(runId: string): number
  /** How much faster the run's clock moves than the wall right now. 1 everywhere real. */
  rate(runId: string): number
}

export const wallClock: RunClock = { now: () => Date.now(), rate: () => 1 }
