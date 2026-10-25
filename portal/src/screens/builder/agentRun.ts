import { ApiError } from '../../api/client'
import type { CardView, CreateAgentUseCase, InputKind } from '../../api/types'
import { detailsOf, REPO, repoFrom } from '../software/addForm'

/** One agent in a run form, with the values typed so far. */
export interface RunAgent {
  readonly card: CardView
  readonly values: Readonly<Record<string, string>>
  /** Input names the Room lead could not find in the task. */
  readonly missing: readonly string[]
}

export const NAME_LIMIT = 80
export const INSTRUCTION_LIMIT = 2000
const PROJECT = /^[A-Z][A-Z0-9]{0,9}$/
const TEXT_LIMIT = 200

export const WORDS = {
  nameMissing: 'Give the use case a name.',
  nameTooLong: `Keep the name to ${NAME_LIMIT} characters.`,
  empty: 'Fill this in.',
  github_repo: 'Write it as owner/name, such as langchain-ai/langgraph.',
  jira_project: 'Write the project key, such as MOCK.',
  text: `Write one line of up to ${TEXT_LIMIT} characters.`,
  gone: 'This agent is no longer available.',
} as const

export function problemKey(agent: number, input: string): string {
  return `${agent}:${input}`
}

/** A value as the platform wants it, so a pasted address or a lower case key still works. */
export function normalized(kind: InputKind, typed: string): string {
  const text = typed.trim()
  if (kind === 'github_repo') return repoFrom(text)
  return kind === 'jira_project' ? text.toUpperCase() : text
}

function valueProblem(kind: InputKind, value: string): string | null {
  if (value === '') return WORDS.empty
  const fits =
    kind === 'github_repo'
      ? REPO.test(value)
      : kind === 'jira_project'
        ? PROJECT.test(value)
        : value.length <= TEXT_LIMIT && !/[\r\n]/.test(value)
  return fits ? null : WORDS[kind]
}

export interface RunProblems {
  readonly name: string | null
  /** Keyed by problemKey. */
  readonly values: Readonly<Record<string, string>>
  /** A problem that is not about one field. */
  readonly form: string | null
}

export type RunChecked =
  { readonly ok: true; readonly body: CreateAgentUseCase } | { readonly ok: false; readonly problems: RunProblems }

export function defaultName(agents: readonly RunAgent[]): string {
  return agents
    .map((agent) => agent.card.name)
    .join(' and ')
    .slice(0, NAME_LIMIT)
}

export function exampleValues(card: CardView): Record<string, string> {
  return Object.fromEntries(card.inputs.map((input) => [input.name, input.example]))
}

/** The values a form starts with: the Room lead's, and nothing for what it could not find. */
export function startValues(agent: RunAgent): Record<string, string> {
  return Object.fromEntries(agent.card.inputs.map((input) => [input.name, agent.values[input.name] ?? '']))
}

export function checkRun(name: string, instruction: string, agents: readonly RunAgent[]): RunChecked {
  const trimmed = name.trim()
  const values: Record<string, string> = {}
  const cleaned = agents.map((agent, at) => {
    const own: Record<string, string> = {}
    for (const input of agent.card.inputs) {
      const value = normalized(input.kind, agent.values[input.name] ?? '')
      const problem = valueProblem(input.kind, value)
      if (problem) values[problemKey(at, input.name)] = problem
      own[input.name] = value
    }
    return { card_id: agent.card.card_id, values: own }
  })
  const nameProblem = trimmed === '' ? WORDS.nameMissing : trimmed.length > NAME_LIMIT ? WORDS.nameTooLong : null
  if (nameProblem || Object.keys(values).length > 0) {
    return { ok: false, problems: { name: nameProblem, values, form: null } }
  }
  const said = instruction.trim().slice(0, INSTRUCTION_LIMIT)
  return { ok: true, body: { name: trimmed, instruction: said === '' ? trimmed : said, agents: cleaned } }
}

/** What the platform refused, as field problems in our words. Null when the error is not a refusal of the form. */
export function refusedRun(error: unknown, agents: readonly RunAgent[]): RunProblems | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null
  let name: string | null = null
  let form: string | null = null
  const values: Record<string, string> = {}
  for (const { loc, msg } of detailsOf(error.body)) {
    const at = loc[0] === 'body' && loc[1] === 'agents' && typeof loc[2] === 'number' ? loc[2] : null
    const agent = at === null ? undefined : agents[at]
    if (at !== null && loc[3] === 'values' && typeof loc[4] === 'string') {
      const kind = agent?.card.inputs.find((input) => input.name === loc[4])?.kind
      values[problemKey(at, loc[4])] = kind ? WORDS[kind] : WORDS.empty
    } else if (at !== null && loc[3] === 'card_id') {
      form = WORDS.gone
    } else if (loc[1] === 'name') {
      name = WORDS.nameTooLong
    } else {
      form = msg.endsWith('.') ? msg : `${msg}.`
    }
  }
  return name || form || Object.keys(values).length > 0 ? { name, values, form } : null
}

/** The first field with a problem, for focus: the name, then each value in page order. */
export function firstRunProblem(problems: RunProblems, agents: readonly RunAgent[]): string | null {
  if (problems.name) return 'name'
  for (const [at, agent] of agents.entries()) {
    for (const input of agent.card.inputs) {
      const key = problemKey(at, input.name)
      if (problems.values[key]) return key
    }
  }
  return null
}
