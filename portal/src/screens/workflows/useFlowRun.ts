import { useQuery } from '@tanstack/react-query'
import { useApiClient, useCacheScope } from '../../api/context'
import { fetchEventPage } from '../../api/queries'
import type { RunView } from '../../api/types'
import type { FlowRun } from './flow'
import { stageOfRun } from './workflow'

/**
 * The latest run's events, from the endpoint the run page reads, cached by the query client. The key holds the run's last event, so the
 * page reads again when the runs list says the run moved on. Null while there is no run, or until its events are read: the diagram then
 * draws the steps without states.
 */
export function useFlowRun(run: RunView | undefined): FlowRun | null {
  const client = useApiClient()
  const user = useCacheScope()
  const lastSeq = run && 'last_seq' in run ? run.last_seq : 0
  const read = useQuery({
    queryKey: ['flow-run', user, run?.run_id ?? '', lastSeq],
    enabled: run !== undefined,
    queryFn: async (): Promise<FlowRun> => {
      const runId = run?.run_id ?? ''
      const events: unknown[] = []
      let after = 0
      for (;;) {
        const page = await fetchEventPage(client, runId, after)
        events.push(...page.events)
        const last = page.events.at(-1)
        if (!last || last.seq <= after) break
        after = last.seq
      }
      return { runId, events, startedAt: run?.started_at ?? '', ...(run ? { stage: stageOfRun(run) } : {}) }
    },
  })
  return read.data ?? null
}
