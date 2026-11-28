import { queryOptions, useQueries } from '@tanstack/react-query'
import type { ApiClient } from '../../api/client'
import { useApiClient, useCacheScope } from '../../api/context'
import { fetchEventPage, keys } from '../../api/queries'

const STALE_MS = 30_000

/** A run to read, and the version it is read at: its state on a board, or its last event on the workflow page. A new version reads again. */
export interface RunRead {
  readonly runId: string
  readonly version: string | number
}

/**
 * How a run is read as steps: its events from the endpoint the run page reads, in one request, under one key. The states of the same
 * run stay on the page while a new version is read, and another run's never do. The app's own retry applies.
 */
export function runStepsOptions(client: ApiClient, user: string, { runId, version }: RunRead) {
  return queryOptions({
    queryKey: keys.runSteps(user, runId, version),
    queryFn: async (): Promise<readonly unknown[]> => (await fetchEventPage(client, runId)).events,
    staleTime: STALE_MS,
    placeholderData: (before: readonly unknown[] | undefined, query) => (query?.queryKey[2] === runId ? before : undefined),
  })
}

/**
 * The events of each run asked for, for a caller that reads many runs at once (the board). A caller that follows one run as it moves on
 * reads it with `useQuery(runStepsOptions(...))`, since only a single observer keeps a run's last data while its next version is read.
 * Here: the events of each run asked for, by run id, read through the query client so a run another screen already read costs nothing. A run that
 * could not be read, or is not read yet, has no entry. The caller bounds the list: the board reads one run per tile it draws.
 */
export function useRunSteps(reads: readonly RunRead[]): ReadonlyMap<string, readonly unknown[]> {
  const client = useApiClient()
  const user = useCacheScope()
  const results = useQueries({ queries: reads.map((read) => runStepsOptions(client, user, read)) })
  const events = new Map<string, readonly unknown[]>()
  reads.forEach(({ runId }, index) => {
    const read = results[index]?.data
    if (read) events.set(runId, read)
  })
  return events
}
