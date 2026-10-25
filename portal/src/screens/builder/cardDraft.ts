import type { CardApprovalView, CardDefinition, CardProblem, InputKind, ToolView } from '../../api/types'

/** A card as the Operator edits it. A block's tool is '' for "no tool". */
export interface CardDraft {
  readonly name: string
  readonly purpose: string
  readonly goodFor: readonly string[]
  readonly inputs: readonly DraftInput[]
  readonly blocks: readonly DraftBlock[]
  /** Kept as the card has them. The platform raises them to each tool's minimum. */
  readonly approvals: readonly CardApprovalView[]
}

export interface DraftInput {
  readonly name: string
  readonly kind: string
  readonly what: string
  readonly example: string
}

export interface DraftBlock {
  readonly say: string
  readonly tool: string
}

/** What a draft is made from: a saved card, or the Room lead's draft. */
interface CardLike {
  readonly name: string
  readonly purpose: string
  readonly good_for?: readonly string[] | undefined
  readonly inputs?: readonly { name: string; kind: string; what?: string; example?: string }[] | undefined
  readonly blocks?: readonly { say: string; tool?: string | null | undefined }[] | undefined
  readonly approvals?: readonly CardApprovalView[] | undefined
}

export const EMPTY_BLOCK: DraftBlock = { say: '', tool: '' }
export const EMPTY_INPUT: DraftInput = { name: '', kind: 'text', what: '', example: '' }

export const KIND_WORDS: Readonly<Record<InputKind, string>> = {
  github_repo: 'GitHub repository',
  jira_project: 'Jira project',
  text: 'Text',
}

export function draftOf(card: CardLike): CardDraft {
  return {
    name: card.name,
    purpose: card.purpose,
    goodFor: card.good_for ?? [],
    inputs: (card.inputs ?? []).map((input) => ({
      name: input.name,
      kind: input.kind,
      what: input.what ?? '',
      example: input.example ?? '',
    })),
    blocks: (card.blocks ?? []).map((block) => ({ say: block.say, tool: block.tool ?? '' })),
    approvals: card.approvals ?? [],
  }
}

/** A copy of a starter agent to change. The Operator can then give it a name of their own. */
export function copyOf(card: CardLike): CardDraft {
  return { ...draftOf(card), name: `${card.name} copy` }
}

export function toDefinition(draft: CardDraft): Required<CardDefinition> {
  return {
    name: draft.name.trim(),
    purpose: draft.purpose.trim(),
    good_for: [...draft.goodFor],
    inputs: draft.inputs.map((input) => ({
      name: input.name.trim(),
      kind: input.kind,
      what: input.what,
      example: input.example.trim(),
    })),
    blocks: draft.blocks.map((block) => ({ say: block.say.trim(), tool: block.tool === '' ? null : block.tool })),
    approvals: [...draft.approvals],
  }
}

export function replaceAt<T>(list: readonly T[], index: number, change: Partial<T>): T[] {
  return list.map((item, at) => (at === index ? { ...item, ...change } : item))
}

export function removeAt<T>(list: readonly T[], index: number): T[] {
  return list.filter((_, at) => at !== index)
}

export interface SortedProblems {
  /** Keyed by "name", "purpose", "blocks.2" or "inputs.0". */
  readonly byField: Readonly<Record<string, readonly string[]>>
  /** Problems that belong to no one field, such as "Add a step". */
  readonly general: readonly string[]
}

const FIELD_KEY = /^(name|purpose|blocks\.\d+|inputs\.\d+)(\..+)?$/

export function sortProblems(problems: readonly CardProblem[]): SortedProblems {
  const byField: Record<string, string[]> = {}
  const general: string[] = []
  for (const { field, message } of problems) {
    const key = field === null ? undefined : FIELD_KEY.exec(field)?.[1]
    if (key === undefined) general.push(message)
    else (byField[key] ??= []).push(message)
  }
  return { byField, general }
}

/** The id of the first field that has a problem, in page order, for focus. */
export function firstProblemKey(sorted: SortedProblems, blocks: number, inputs: number): string | null {
  const order = [
    'name',
    'purpose',
    ...Array.from({ length: inputs }, (_, at) => `inputs.${at}`),
    ...Array.from({ length: blocks }, (_, at) => `blocks.${at}`),
  ]
  return order.find((key) => sorted.byField[key] !== undefined) ?? null
}

export function toolName(tools: readonly ToolView[] | undefined, id: string): string {
  return tools?.find((tool) => tool.id === id)?.name ?? id
}

/** One line for each approval the card needs. Empty when the agent only reads. */
export function approvalWords(approvals: readonly CardApprovalView[], tools: readonly ToolView[] | undefined): string[] {
  return approvals.map(
    ({ tool, approvers }) =>
      `${toolName(tools, tool)}: ${approvers === 1 ? 'one Approver' : `${approvers} Approvers`} must approve it first.`,
  )
}
