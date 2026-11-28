import { useQuery } from '@tanstack/react-query'
import { useApiClient, useCacheScope } from '../../api/context'
import type { RunView } from '../../api/types'
import { runStepsOptions } from '../run/useRunSteps'
import type { FlowRun } from './flow'
import { runAt, stageOfRun } from './workflow'

const NO_RUN = { runId: '', version: 0 }

/**
 * The latest run's events for the flow diagram, from the one per-run read, at the run's last event. One observer reads it, so while a
 * live run moves on its states stay on the page, and another run's never do. Null while there is no run, or until its events are read: the
 * diagram then draws the steps without states.
 */
export function useFlowRun(run: RunView | undefined): FlowRun | null {
  const client = useApiClient()
  const user = useCacheScope()
  const read = useQuery({ ...runStepsOptions(client, user, run ? { runId: run.run_id, version: run.last_seq } : NO_RUN), enabled: run !== undefined })
  return run && read.data ? { runId: run.run_id, events: read.data, startedAt: runAt(run), stage: stageOfRun(run) } : null
}
