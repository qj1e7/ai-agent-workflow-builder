export interface RunClock {
  /** Now on the run's own timeline: the wall live, the demo platform's paced clock in demo mode. */
  now(runId: string): number
  /** How much faster the run's clock moves than the wall right now. 1 everywhere real. */
  rate(runId: string): number
}

export const wallClock: RunClock = { now: () => Date.now(), rate: () => 1 }
