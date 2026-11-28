import type { RunView } from '../../api/types'
import { useRunSteps } from '../run/useRunSteps'
import type { FlowRun } from './flow'
import { runAt, stageOfRun } from './workflow'

/**
 * The latest run's events for the flow diagram, from the one per-run read, at the run's last event. Null while there is no run, or until its
 * events are read: the diagram then draws the steps without states.
 */
export function useFlowRun(run: RunView | undefined): FlowRun | null {
  const events = useRunSteps(run ? [{ runId: run.run_id, version: run.last_seq }] : [])
  const read = run ? events.get(run.run_id) : undefined
  return run && read ? { runId: run.run_id, events: read, startedAt: runAt(run), stage: stageOfRun(run) } : null
}
