import type { RunView, RunViewOf } from '../../api/types'

export function waitingApprovals(runs: readonly RunView[]): RunViewOf<'awaiting_approval'>[] {
  return runs
    .filter((run): run is RunViewOf<'awaiting_approval'> => run.state === 'awaiting_approval')
    .sort((a, b) => Date.parse(a.updated_at) - Date.parse(b.updated_at))
}
