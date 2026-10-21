import { useTemplates, useUseCase } from '../api/queries'
import type { RunView, TemplateView } from '../api/types'

/** The template behind a run's use case, once both have loaded: its name and the blocks its line is drawn from. */
export function useRunTemplate(run: RunView | undefined): TemplateView | undefined {
  const useCase = useUseCase(run?.use_case_id ?? '', run !== undefined)
  const templates = useTemplates()
  const key = useCase.data?.template
  return key ? templates.data?.find((template) => template.key === key) : undefined
}
