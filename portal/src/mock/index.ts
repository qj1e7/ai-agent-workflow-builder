import type { RunClock } from '../api/clock'
import { readRequest } from './http'
import { DemoPlatform } from './platform'
import { dispatch } from './routes'

export interface DemoPlatformHandle {
  readonly fetch: typeof fetch
  /** The recorded time of a run now, which runs ahead of the wall clock while a long wait is squeezed. */
  readonly now: RunClock
}

export function createDemoPlatform(start: number = Date.now()): DemoPlatformHandle {
  const platform = new DemoPlatform(start)
  return {
    fetch: async (input, init) => dispatch(platform, await readRequest(input, init), Date.now()),
    now: (runId) => platform.clock(runId, Date.now()),
  }
}
