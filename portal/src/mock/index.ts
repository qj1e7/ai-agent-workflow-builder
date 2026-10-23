import type { RunClock } from '../api/clock'
import { readRequest } from './http'
import { DemoPlatform } from './platform'
import { dispatch } from './routes'

export interface DemoPlatformHandle {
  readonly fetch: typeof fetch
  readonly clock: RunClock
}

export function createDemoPlatform(start: number = Date.now()): DemoPlatformHandle {
  const platform = new DemoPlatform(start)
  return {
    fetch: async (input, init) => dispatch(platform, await readRequest(input, init), Date.now()),
    clock: {
      now: (runId) => platform.clock(runId, Date.now()),
      rate: (runId) => platform.clockRate(runId, Date.now()),
    },
  }
}
