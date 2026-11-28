import { queryOptions, useQuery } from '@tanstack/react-query'
import type { ApiClient } from '../../api/client'
import { useApiClient, useCacheScope } from '../../api/context'
import { fetchEventPage, keys } from '../../api/queries'
import type { RunView } from '../../api/types'
import type { FlowRun } from './flow'
import { runAt, stageOfRun } from './workflow'

/**
 * How the latest run is read: its events from the endpoint the run page reads, in one request. The key holds the run's last event, so the
 * page reads again when the runs list says the run moved on, and the states of the same run stay on the page while it does. Another run's
 * states never do.
 */
export function flowRunOptions(client: ApiClient, user: string, run: RunView) {
  return queryOptions({
    queryKey: keys.runFlow(user, run.run_id, run.last_seq),
    queryFn: async (): Promise<FlowRun> => {
      const { events } = await fetchEventPage(client, run.run_id)
      return { runId: run.run_id, events, startedAt: runAt(run), stage: stageOfRun(run) }
    },
    placeholderData: (before: FlowRun | undefined) => (before?.runId === run.run_id ? before : undefined),
  })
}

/** The latest run's events for the flow diagram. Null while there is no run, or until its events are read: the diagram then draws the steps without states. */
export function useFlowRun(run: RunView | undefined): FlowRun | null {
  const client = useApiClient()
  const user = useCacheScope()
  const read = useQuery({ ...flowRunOptions(client, user, run ?? NO_RUN), enabled: run !== undefined })
  return run === undefined ? null : (read.data ?? null)
}

const NO_RUN = { run_id: '', last_seq: 0 } as unknown as RunView
