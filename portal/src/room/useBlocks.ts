import { useTemplates, useUseCase } from '../api/queries'
import type { BlockView, RunView } from '../api/types'

/** The blocks of the template behind a run's use case, once both have loaded. */
export function useBlocks(run: RunView | undefined): readonly BlockView[] | undefined {
  const useCase = useUseCase(run?.use_case_id ?? '', run !== undefined)
  const templates = useTemplates()
  const key = useCase.data?.template
  return key ? templates.data?.find((template) => template.key === key)?.blocks : undefined
}
