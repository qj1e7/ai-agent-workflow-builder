import type {
  CardDefinition,
  CreateAgentUseCase,
  Day,
  DraftView,
  InputKind,
  PlanOut,
  RowKind,
  RowState,
  ScheduleIn,
  ToolId,
  UnderstandOut,
  UseCaseCreated,
} from '../../api/types'
import { checkClock, checkRepo, repeatWords, repoOf } from '../software/software'

export type Step = 1 | 2 | 3 | 4
export const STEP_NAMES = ['Describe it', 'Check what I understood', 'When it runs', 'Turn it on'] as const

export const TEXT_LIMIT = 2000
export const NAME_LIMIT = 80
const VALUE_LIMIT = 200
const DRAFT_NAME_LIMIT = 60

export type ChipState = RowState | 'edited'

export interface PlannerRow {
  readonly text: string
  readonly state: RowState
  readonly note: string | null
}

export interface Row {
  readonly kind: RowKind
  readonly text: string
  readonly state: ChipState
  readonly note: string | null
  readonly planner: PlannerRow | null
}

export interface Redirect {
  readonly word: string
  readonly software: string | null
  readonly note: string
}

export type Often = '' | 'every_day' | 'weekdays' | 'week'
export type Weekday = Exclude<Day, 'every_day' | 'weekdays'>

export interface When {
  readonly often: Often
  readonly day: Weekday | ''
  readonly at: string
  readonly filledFrom: string | null
}

export interface Form {
  readonly step: Step
  readonly text: string
  readonly rows: readonly Row[]
  readonly redirect: Redirect | null
  readonly plannerSaid: string | null
  readonly typed: Readonly<Record<string, string>>
  readonly when: When
  readonly name: string
}

export const EMPTY_WHEN: When = { often: '', day: '', at: '', filledFrom: null }

export const EMPTY_FORM: Form = { step: 1, text: '', rows: [], redirect: null, plannerSaid: null, typed: {}, when: EMPTY_WHEN, name: '' }

export const ROW_LABEL: Record<RowKind, string> = { schedule: 'When', look_for: 'Looks for', do: 'Does', where: 'Where it goes' }

const SAY_IT: Record<RowKind, string> = {
  schedule: 'you say when it runs',
  look_for: 'you say what to look for',
  do: 'you say what it does',
  where: 'you say where it goes',
}
const CHANGE_IT = 'you change what I can’t do'
const KINDS: readonly RowKind[] = ['schedule', 'look_for', 'do', 'where']

export function textProblem(text: string): string | null {
  if (text.trim() === '') return 'Write what should happen first.'
  return text.trim().length > TEXT_LIMIT ? 'Keep it to 2,000 characters.' : null
}

export function afterReading(form: Form, answer: UnderstandOut): Form {
  switch (answer.answer) {
    case 'rows':
      return {
        ...form,
        step: 2,
        plannerSaid: null,
        redirect: null,
        when: EMPTY_WHEN,
        rows: answer.rows.map((row) => ({ kind: row.kind, text: row.text, state: row.state, note: row.note, planner: null })),
      }
    case 'watchlist':
      return { ...form, step: 2, plannerSaid: null, rows: [], when: EMPTY_WHEN, redirect: { word: answer.word, software: answer.software, note: answer.note } }
    case 'starters':
      return { ...form, step: 1, plannerSaid: answer.message }
  }
}

export function carryOn(form: Form): Form {
  return { ...form, step: 2, redirect: null, rows: KINDS.map((kind) => ({ kind, text: '', state: 'missing', note: null, planner: null })) }
}

export function changeRow(form: Form, index: number, typed: string): Form {
  const rows = form.rows.map((row, at): Row => {
    if (at !== index) return row
    const planner = row.planner ?? { text: row.text, state: row.state as RowState, note: row.note }
    const text = typed.trim()
    if (text === planner.text) return { kind: row.kind, ...planner, planner: null }
    if (text === '') return { kind: row.kind, text: '', state: 'missing', note: null, planner }
    return { kind: row.kind, text, state: 'edited', note: null, planner }
  })
  return { ...form, rows }
}

export function canDrop(rows: readonly Row[], index: number): boolean {
  const row = rows[index]
  return row !== undefined && rows.some((other, at) => at !== index && other.kind === row.kind)
}

export function dropRow(form: Form, index: number): Form {
  return canDrop(form.rows, index) ? { ...form, rows: form.rows.filter((_, at) => at !== index) } : form
}

export interface Blocker {
  readonly index: number
  readonly words: string
}

export function rowBlockers(rows: readonly Row[]): Blocker[] {
  const out: Blocker[] = []
  rows.forEach((row, index) => {
    const words = row.state === 'missing' ? SAY_IT[row.kind] : row.state === 'cant_do' ? CHANGE_IT : null
    if (words !== null && !out.some((blocker) => blocker.words === words)) out.push({ index, words })
  })
  return out
}

const withoutStop = (text: string) => text.trim().replace(/[.!?]+$/, '')
export const lowerFirst = (text: string) => (/^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text)
const upperFirst = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

export function textsOf(rows: readonly Row[], kind: RowKind): string[] {
  return rows.filter((row) => row.kind === kind && row.text !== '').map((row) => withoutStop(row.text))
}

export function taskWithoutSchedule(rows: readonly Row[]): string {
  const looks = textsOf(rows, 'look_for').map(lowerFirst).join(' and ')
  const does = textsOf(rows, 'do').join(' and ')
  const where = textsOf(rows, 'where').join(' and ')
  return [looks ? `Find ${looks}.` : '', does ? `${upperFirst(does)}.` : '', where ? `Where it goes: ${where}.` : ''].filter(Boolean).join(' ')
}

export interface AgentInput {
  readonly name: string
  readonly kind: InputKind
  readonly what: string
}

export interface PlanAgent {
  readonly index: number
  readonly name: string
  readonly card: { readonly kind: 'saved'; readonly id: string } | { readonly kind: 'drafted'; readonly definition: CardDefinition }
  readonly inputs: readonly AgentInput[]
  readonly blocks: readonly { readonly say: string; readonly tool: ToolId | null }[]
  readonly found: Readonly<Record<string, string>>
}

export type PlanView =
  | { readonly kind: 'agents'; readonly agents: readonly PlanAgent[]; readonly problems: readonly string[]; readonly notIncluded: readonly string[] }
  | { readonly kind: 'cannot'; readonly reason: string; readonly missing: readonly string[] }
  | { readonly kind: 'trouble'; readonly message: string }

const INPUT_KINDS: readonly InputKind[] = ['github_repo', 'jira_project', 'text']
const PROJECT_IN = /\b(?:project|in)\s+([A-Z][A-Z0-9]{1,9})\b/
const REPO_IN = /(?:github\.com\/)?\b([A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+)/

function foundIn(rows: readonly Row[], kind: InputKind): string | null {
  const words = rows.filter((row) => row.kind !== 'schedule').map((row) => row.text).join(' \n ')
  if (kind === 'jira_project') return PROJECT_IN.exec(words)?.[1] ?? null
  if (kind === 'github_repo') return REPO_IN.exec(words)?.[1] ?? null
  return null
}

const toolOf = (tool: string | null | undefined): ToolId | null => (tool ? (tool as ToolId) : null)

export function planView(answer: PlanOut, rows: readonly Row[]): PlanView {
  switch (answer.decision) {
    case 'use_one':
    case 'use_several':
      return {
        kind: 'agents',
        problems: [],
        notIncluded: [],
        agents: answer.agents.map((agent, index) => ({
          index,
          name: agent.card.name,
          card: { kind: 'saved', id: agent.card.card_id },
          inputs: agent.card.inputs.map(({ name, kind, what }) => ({ name, kind, what })),
          blocks: agent.card.blocks,
          found: agent.values,
        })),
      }
    case 'new_agent': {
      const inputs = (answer.draft.inputs ?? []).map(({ name, kind, what }) => ({
        name,
        kind: INPUT_KINDS.includes(kind as InputKind) ? (kind as InputKind) : 'text',
        what: what ?? '',
      }))
      const found = Object.fromEntries(inputs.flatMap((input) => {
        const value = foundIn(rows, input.kind)
        return value === null ? [] : [[input.name, value]]
      }))
      return {
        kind: 'agents',
        problems: answer.problems.map((problem) => problem.message),
        notIncluded: answer.missing_tools.map((tool) => tool.need),
        agents: [
          {
            index: 0,
            name: answer.draft.name,
            card: { kind: 'drafted', definition: answer.draft },
            inputs,
            blocks: (answer.draft.blocks ?? []).map((block) => ({ say: block.say, tool: toolOf(block.tool) })),
            found,
          },
        ],
      }
    }
    case 'cannot_do':
      return { kind: 'cannot', reason: answer.reason, missing: answer.missing_tools.map((tool) => tool.need) }
    case 'model_problem':
      return { kind: 'trouble', message: answer.message }
  }
}

export const valueKey = (agent: number, input: string) => `${agent}:${input}`

export function valueOf(form: Form, agent: PlanAgent, input: string): string {
  return form.typed[valueKey(agent.index, input)] ?? agent.found[input] ?? ''
}

const PROJECT = /^[A-Z][A-Z0-9]{0,9}$/

function normalised(kind: InputKind, value: string): string {
  const text = value.trim()
  if (kind === 'github_repo') return repoOf(text)
  return kind === 'jira_project' ? text.toUpperCase() : text
}

export function valueProblem(kind: InputKind, value: string): string | null {
  const text = normalised(kind, value)
  if (text === '') return 'Fill this in.'
  if (kind === 'github_repo') return checkRepo(text).ok ? null : 'Write it as owner/name, such as langchain-ai/langgraph.'
  if (kind === 'jira_project') return PROJECT.test(text) ? null : 'Write the project key, such as MOCK.'
  return text.length <= VALUE_LIMIT && !/[\r\n]/.test(text) ? null : `Write one line of up to ${VALUE_LIMIT} characters.`
}

export interface NextBlockers {
  readonly rows: readonly Blocker[]
  readonly words: string
}

function opensWhen(parts: readonly string[]): string {
  return parts.length === 0 ? '' : `Next opens when ${parts.join(' and ')}.`
}

export function nextBlockers(form: Form, plan: PlanView | null): NextBlockers {
  const rows = rowBlockers(form.rows)
  if (rows.length > 0) return { rows, words: opensWhen(rows.map((blocker) => blocker.words)) }
  if (plan === null) return { rows, words: opensWhen(['the plan is ready']) }
  if (plan.kind === 'cannot') return { rows, words: opensWhen(['you change your words to something I can do']) }
  if (plan.kind === 'trouble') return { rows, words: opensWhen(['the Planner can read it']) }
  if (plan.problems.length > 0) return { rows, words: opensWhen(['you change your words so the new agent has no problems']) }
  if (plan.notIncluded.length > 0) return { rows, words: opensWhen(['you change your words so nothing is left out']) }
  const empty = plan.agents.flatMap((agent) => agent.inputs.filter((input) => valueProblem(input.kind, valueOf(form, agent, input.name)) !== null).map((input) => input.name))
  return { rows, words: empty.length > 0 ? opensWhen([`you fill in ${[...new Set(empty)].join(' and ')}`]) : '' }
}

const DAY_NAMES: readonly Weekday[] = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

function clockIn(text: string): string {
  const twelve = /\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b/.exec(text)
  if (twelve && Number(twelve[1]) >= 1 && Number(twelve[1]) <= 12) {
    const hour = (Number(twelve[1]) % 12) + (twelve[3] === 'pm' ? 12 : 0)
    return `${String(hour).padStart(2, '0')}:${twelve[2] ?? '00'}`
  }
  const day = /\b([01]?\d|2[0-3])[:.]([0-5]\d)\b/.exec(text)
  if (day) return `${(day[1] ?? '').padStart(2, '0')}:${day[2] ?? ''}`
  return /\b(?:noon|midday)\b/.test(text) ? '12:00' : ''
}

export function readWhen(said: string): When {
  const text = ` ${said.toLowerCase()} `
  const named = DAY_NAMES.find((day) => new RegExp(`\\b${day}s?\\b`).test(text))
  let often: Often = ''
  let day: Weekday | '' = ''
  if (/\b(?:every|each) ?week ?days?\b|\bweekdays\b|\bmonday to friday\b/.test(text)) often = 'weekdays'
  else if (named) {
    often = 'week'
    day = named
  } else if (/\b(?:every|each) (?:day|morning|evening)\b|\bdaily\b/.test(text)) often = 'every_day'
  return { often, day, at: clockIn(text), filledFrom: said }
}

export function enterWhen(form: Form): Form {
  const said = form.rows.find((row) => row.kind === 'schedule')?.text ?? ''
  if (form.when.filledFrom === said) return form
  return { ...form, when: readWhen(said) }
}

export type WhenField = 'often' | 'day' | 'at'

export function whenProblems(when: When): Partial<Record<WhenField, string>> {
  const out: Partial<Record<WhenField, string>> = {}
  if (when.often === '') out.often = 'Choose how often it runs.'
  if (when.often === 'week' && when.day === '') out.day = 'Choose a day.'
  if (when.at === '') out.at = 'Choose a time.'
  else {
    const clock = checkClock(when.at)
    if (!clock.ok) out.at = clock.words
  }
  return out
}

export function scheduleOf(when: When): ScheduleIn {
  const day: Day = when.often === 'week' ? (when.day === '' ? 'monday' : when.day) : when.often === '' ? 'every_day' : when.often
  return { day, at: when.at }
}

export function whenWords(when: When): string {
  return upperFirst(repeatWords(scheduleOf(when)))
}

export function defaultName(plan: PlanView | null): string {
  if (plan?.kind !== 'agents') return ''
  return plan.agents.map((agent) => agent.name).join(' and ').slice(0, NAME_LIMIT)
}

export function nameProblem(name: string): string | null {
  if (name.trim() === '') return 'Give the workflow a name.'
  return name.trim().length > NAME_LIMIT ? `Keep the name to ${NAME_LIMIT} characters.` : null
}

export function nameOf(form: Form, plan: PlanView | null): string {
  return form.name.trim() || defaultName(plan)
}

export interface Checked {
  readonly ok: boolean
  readonly words: string
}

function sameWhen(a: When, b: When): boolean {
  return a.often === b.often && (a.often !== 'week' || a.day === b.day) && a.at === b.at
}

export function checkedRows(form: Form): Checked[] {
  return form.rows.map((row) => {
    const label = ROW_LABEL[row.kind]
    if (row.kind === 'schedule') {
      const chosen = whenWords(form.when)
      const asked = row.text
      if (asked !== '' && sameWhen(readWhen(asked), form.when)) return { ok: true, words: `${label}: ${chosen}, as you asked.` }
      return { ok: false, words: asked !== '' ? `${label}: ${chosen}. You asked for “${asked}”.` : `${label}: ${chosen}. You chose this.` }
    }
    if (row.state === 'edited') return { ok: false, words: `${label}: ${row.text}. You changed this.` }
    if (row.state === 'changed') return { ok: false, words: `${label}: ${row.text}. ${row.note ?? ''}`.trim() }
    return { ok: true, words: `${label}: ${row.text}, as you asked.` }
  })
}

export function createBody(form: Form, plan: PlanView, savedDrafts: Readonly<Record<number, string>>): CreateAgentUseCase {
  const agents = plan.kind === 'agents' ? plan.agents : []
  return {
    name: nameOf(form, plan),
    instruction: taskWithoutSchedule(form.rows),
    agents: agents.map((agent) => ({
      card_id: agent.card.kind === 'saved' ? agent.card.id : (savedDrafts[agent.index] ?? notSavedYet(agent)),
      values: Object.fromEntries(agent.inputs.map((input) => [input.name, normalised(input.kind, valueOf(form, agent, input.name))])),
    })),
    schedule: scheduleOf(form.when),
  }
}

function notSavedYet(agent: PlanAgent): never {
  throw new Error(`${agent.name} is a drafted agent that has not been saved yet.`)
}

export interface TurnOnCalls {
  readonly saveCard: (card: CardDefinition) => Promise<string>
  readonly create: (body: CreateAgentUseCase) => Promise<UseCaseCreated>
  readonly deleteDraft: (draftId: string) => Promise<unknown>
}

export interface TurnedOn {
  readonly useCaseId: string
  readonly draftKept: boolean
}

export async function turnOn(form: Form, plan: PlanView, draftId: string | null, cards: Map<string, string>, calls: TurnOnCalls): Promise<TurnedOn> {
  const task = taskWithoutSchedule(form.rows)
  const saved: Record<number, string> = {}
  for (const agent of plan.kind === 'agents' ? plan.agents : []) {
    if (agent.card.kind === 'saved') continue
    const key = `${task}#${String(agent.index)}`
    const id = cards.get(key) ?? (await calls.saveCard(agent.card.definition))
    cards.set(key, id)
    saved[agent.index] = id
  }
  const made = await calls.create(createBody(form, plan, saved))
  const draftKept = draftId !== null && (await calls.deleteDraft(draftId).then(() => false, () => true))
  return { useCaseId: made.use_case_id, draftKept }
}

export interface Planned {
  readonly task: string
  readonly answer: PlanOut
}

function excerpt(text: string): string | null {
  const flat = text.trim().replace(/\s+/g, ' ')
  if (flat === '') return null
  return flat.length <= DRAFT_NAME_LIMIT ? flat : `${flat.slice(0, DRAFT_NAME_LIMIT).replace(/\s+\S*$/, '')}…`
}

export function draftContent(form: Form, plan: Planned | null): DraftView['content'] {
  const name = form.name.trim() || (plan ? defaultName(planView(plan.answer, form.rows)) : '') || excerpt(form.text)
  return { name: name || null, form, plan }
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const isString = (value: unknown): value is string => typeof value === 'string'
const STEPS: readonly unknown[] = [1, 2, 3, 4]
const ROW_STATES: readonly unknown[] = ['understood', 'changed', 'missing', 'cant_do', 'edited']
const OFTEN: readonly unknown[] = ['', 'every_day', 'weekdays', 'week']

function isRow(value: unknown): value is Row {
  return isRecord(value) && KINDS.includes(value['kind'] as RowKind) && isString(value['text']) && ROW_STATES.includes(value['state'])
}

function isForm(value: unknown): value is Form {
  if (!isRecord(value) || !STEPS.includes(value['step']) || !isString(value['text']) || !isString(value['name'])) return false
  const when = value['when']
  return (
    Array.isArray(value['rows']) &&
    value['rows'].every(isRow) &&
    isRecord(value['typed']) &&
    Object.values(value['typed']).every(isString) &&
    isRecord(when) &&
    OFTEN.includes(when['often']) &&
    isString(when['at'])
  )
}

function isPlanned(value: unknown): value is Planned {
  return isRecord(value) && isString(value['task']) && isRecord(value['answer']) && isString(value['answer']['decision'])
}

export function restoreDraft(draft: DraftView): { readonly form: Form; readonly plan: Planned | null } {
  const { form, plan, text, intent } = draft.content as Record<string, unknown>
  if (isForm(form)) return { form, plan: isPlanned(plan) ? plan : null }
  const task = isString(text) ? text : isString(intent) ? intent : ''
  return { form: { ...EMPTY_FORM, text: task }, plan: null }
}
