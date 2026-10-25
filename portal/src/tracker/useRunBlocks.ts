import { useUseCase } from '../api/queries'
import type { BlockView, RunView } from '../api/types'

/** The blocks a run's line is drawn from: the plan of its use case, once it has loaded. */
export function useRunBlocks(run: RunView | undefined): readonly BlockView[] | undefined {
  return useUseCase(run?.use_case_id ?? '', run !== undefined).data?.plan
}
