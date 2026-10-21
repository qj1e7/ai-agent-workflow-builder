import type { CreateUseCase, ParamSpec, TemplateView } from '../../api/types'
import type { SpineBlock } from '../../ui/Spine'

export const EXAMPLE_TASK =
  'Every Monday, check langchain-ai/langgraph on GitHub for new releases. If there are any, open a Jira ticket for the team.'

export const NO_MATCH_WORDS =
  'The Room lead could not match this to a ready-made plan yet. Try naming the system and the action, for example GitHub releases and a Jira ticket.'

export const FILL_IN_WORDS = 'Fill this in before saving.'

export function planBlocks(template: TemplateView): SpineBlock[] {
  return template.blocks.map((block) => ({
    key: block.key,
    name: block.name,
    kind: block.kind,
    description: block.description,
    state: { kind: 'not_reached' },
  }))
}

/** Details the template fixes. The platform refuses any other value, so the Operator never types them. */
const FIXED_PARAMS: ReadonlySet<string> = new Set(['tag_pattern'])

export function editableParams(template: TemplateView): ParamSpec[] {
  return template.params.filter((param) => !FIXED_PARAMS.has(param.name))
}

export function fixedParams(template: TemplateView): ParamSpec[] {
  return template.params.filter((param) => FIXED_PARAMS.has(param.name))
}

export interface FieldWords {
  label: string
  help: string | null
}

export function fieldWords(description: string): FieldWords {
  const text = description.trim()
  const end = text.indexOf('. ')
  if (end === -1) return { label: text, help: null }
  const help = text.slice(end + 2).trim()
  return { label: text.slice(0, end), help: help === '' ? null : help }
}

export function exampleParams(template: TemplateView): Record<string, string> {
  return Object.fromEntries(template.params.map((param) => [param.name, param.example]))
}

export interface UseCaseDraft {
  name: string
  params: Readonly<Record<string, string>>
}

export interface DraftProblems {
  name: string | null
  params: Record<string, string>
}

export function draftProblems(template: TemplateView, draft: UseCaseDraft): DraftProblems {
  const empty = (text: string | undefined) => (text ?? '').trim() === ''
  return {
    name: empty(draft.name) ? 'Give the use case a name.' : null,
    params: Object.fromEntries(
      editableParams(template).filter((param) => empty(draft.params[param.name])).map((param) => [param.name, FILL_IN_WORDS]),
    ),
  }
}

export function hasProblems(problems: DraftProblems): boolean {
  return problems.name !== null || Object.keys(problems.params).length > 0
}

export function createBody(template: TemplateView, instruction: string, draft: UseCaseDraft): CreateUseCase {
  return {
    template: template.key,
    name: draft.name.trim(),
    instruction: instruction.trim(),
    params: Object.fromEntries(template.params.map((param) => [param.name, (draft.params[param.name] ?? '').trim()])),
  }
}
