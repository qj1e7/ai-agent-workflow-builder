import type { CreateUseCase, TemplateView } from '../../api/types'

export const EXAMPLE_TASK =
  'Every Monday, check langchain-ai/langgraph on GitHub for new releases. If there are any, open a Jira ticket for the team.'

export function exampleParams(template: TemplateView): Record<string, string> {
  return Object.fromEntries(template.params.map((param) => [param.name, param.example]))
}

export function createBody(
  template: TemplateView,
  instruction: string,
  draft: { name: string; params: Readonly<Record<string, string>> },
): CreateUseCase {
  return {
    template: template.key,
    name: draft.name.trim(),
    instruction: instruction.trim(),
    params: Object.fromEntries(template.params.map((param) => [param.name, (draft.params[param.name] ?? '').trim()])),
  }
}
