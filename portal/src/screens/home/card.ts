import type {
  CardDefinition,
  CardView,
  CreateAgentUseCase,
  Day,
  DraftView,
  InputKind,
  PartReason,
  PartView,
  PlanOut,
  RowKind,
  RowState,
  ScheduleIn,
  ToolId,
  UseCaseCreated,
} from '../../api/types'
import { checkClock, checkRepo, clockWords, repeatWords, repoOf } from '../software/software'

export type Step = 1 | 2 | 3 | 4

export const NAME_LIMIT = 80
const VALUE_LIMIT = 200
const DRAFT_NAME_LIMIT = 60

export type ChipState = RowState | 'edited' | 'checking'

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
  readonly typed: Readonly<Record<string, string>>
  readonly when: When
  readonly name: string
  /** The Operator chose a new workflow over the Software watchlist, so each part is checked as a part, never sent to the watchlist. */
  readonly carriedOn: boolean
  /** Each part of her request the Planner marked with a cross or a question (spec 6.5). A tick needs no keeping, since the rows hold what it will do. */
  readonly marked: readonly PartView[]
}

export const EMPTY_WHEN: When = { often: '', day: '', at: '', filledFrom: null }

export const EMPTY_FORM: Form = { step: 1, text: '', rows: [], typed: {}, when: EMPTY_WHEN, name: '', carriedOn: false, marked: [] }

export const ROW_LABEL: Record<RowKind, string> = { schedule: 'When', look_for: 'Looks for', do: 'Does', where: 'Where it goes' }

const SAY_IT: Record<RowKind, string> = {
  schedule: 'you say when it runs',
  look_for: 'you say what to look for',
  do: 'you say what it does',
  where: 'you say where it goes',
}
const CHANGE_IT = 'you change what I can’t do'
const CHECK_IT = 'I’ve checked your new words'
const NOT_CHECKED = 'I couldn’t check your new words just now. Change them to try again.'
const CANT_YET = 'I can’t do this yet.'
const KINDS: readonly RowKind[] = ['schedule', 'look_for', 'do', 'where']

export function changeRow(form: Form, index: number, typed: string): Form {
  const rows = form.rows.map((row, at): Row => {
    if (at !== index) return row
    const planner = row.planner ?? { text: row.text, state: row.state as RowState, note: row.note }
    const text = typed.trim()
    if (text === planner.text) return { kind: row.kind, ...planner, planner: null }
    if (text === '') return { kind: row.kind, text: '', state: 'missing', note: null, planner }
    return { kind: row.kind, text, state: 'checking', note: null, planner }
  })
  // Her new words for the tickets replace the ones the Planner asked how many days about.
  const marked = form.rows[index]?.kind === 'look_for' ? form.marked.filter((part) => part.reason !== 'how_many_days') : form.marked
  return { ...form, rows, marked }
}

type Part = Pick<Row, 'kind' | 'text'>

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

function blockedBy(row: Row): string | null {
  if (row.state === 'missing') return SAY_IT[row.kind]
  if (row.state === 'cant_do') return CHANGE_IT
  return row.state === 'checking' ? CHECK_IT : null
}

export function rowBlockers(rows: readonly Row[]): Blocker[] {
  const out: Blocker[] = []
  rows.forEach((row, index) => {
    const words = blockedBy(row)
    if (words !== null && !out.some((blocker) => blocker.words === words)) out.push({ index, words })
  })
  return out
}

const withoutStop = (text: string) => text.trim().replace(/[.!?]+$/, '')
const NAMES = /^(Jira|Teams|GitHub|GitLab|Confluence|Slack|Outlook|Entra)\b/

export const lowerFirst = (text: string) => (/^[A-Z][a-z]/.test(text) && !NAMES.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text)
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
const PROJECT_IN = /\b(?:project|in)\s+([A-Z][A-Z0-9_]{1,9})\b/
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

// Jira's own shape (ADR 0035): a capital letter, then capital letters, digits or underscores.
const PROJECT = /^[A-Z][A-Z0-9_]{1,254}$/

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
  // “at 17” can only mean 17:00. “at 9” could be 9:00 or 21:00, so it is asked (bareHour).
  const late = BARE_HOUR.exec(text)
  if (late && Number(late[1]) >= 13 && Number(late[1]) <= 23) return `${late[1] ?? ''}:00`
  return /\b(?:noon|midday)\b/.test(text) ? '12:00' : ''
}

const BARE_HOUR = /\bat\s+(\d{1,2})\b(?![:.]\d)(?!\s*(?:am|pm)\b)/i

/** The two times a bare hour could mean, morning first: 9 is 9:00 or 21:00, and 12 is 0:00 or 12:00. */
export const hourChoices = (hour: number): readonly [string, string] => [`${String(hour % 12).padStart(2, '0')}:00`, `${String((hour % 12) + 12)}:00`]

/** The hour of “at 9”, which could be morning or evening. Null when the words name no such hour. */
export function bareHour(said: string): number | null {
  const found = BARE_HOUR.exec(said)
  const hour = found ? Number(found[1]) : NaN
  return hour >= 1 && hour <= 12 ? hour : null
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

const OFTEN_NAMES: Readonly<Record<Exclude<Often, ''>, string>> = { every_day: 'Every day', weekdays: 'Every weekday', week: 'Every week' }
const DAY_WORD = (day: Weekday) => day.charAt(0).toUpperCase() + day.slice(1)
const CLASHES: readonly PartReason[] = ['one_frequency', 'one_day', 'one_time']

/** Two days, two times or two frequencies in one schedule. The card asks which one, and never picks the first (spec 6.6). */
export const isClash = (part: PartView): boolean => part.mark === 'cant' && part.reason !== null && CLASHES.includes(part.reason)

function oftenOf(words: string): Often {
  const text = words.toLowerCase()
  if (/\bweek ?days?\b|\bmonday to friday\b/.test(text)) return 'weekdays'
  if (/\b(?:day|daily|morning|evening)\b/.test(text)) return 'every_day'
  return /\bweek(?:ly)?\b/.test(text) ? 'week' : ''
}

const dayOf = (words: string): Weekday | '' => DAY_NAMES.find((day) => new RegExp(`^${day}s?$`).test(words.trim().toLowerCase())) ?? ''

/** What one of a clash’s choices sets on the schedule, or null when the choice can’t be read as one. */
function clashSet(reason: PartView['reason'], choice: string): Partial<When> | null {
  if (reason === 'one_frequency') {
    const often = oftenOf(choice)
    return often === '' ? null : { often }
  }
  if (reason === 'one_day') {
    const day = dayOf(choice)
    return day === '' ? null : { often: 'week', day }
  }
  if (reason === 'one_time') {
    const at = clockIn(` ${choice.toLowerCase()} `)
    return at === '' ? null : { at }
  }
  return null
}

/** The choice of a clash the schedule holds now, in her words, or null while it holds none of them. */
export function clashChosen(when: When, part: PartView): string | null {
  return part.choices.find((choice) => {
    const set = clashSet(part.reason, choice)
    return set !== null && (Object.keys(set) as (keyof When)[]).every((field) => when[field] === set[field])
  }) ?? null
}

/** Her words for each part with a cross. After she picks one of a clash’s choices, only the others are left out. */
export function leftOutOf(form: Form): string[] {
  return form.marked.flatMap((part) => {
    if (part.mark !== 'cant') return []
    const chosen = isClash(part) ? clashChosen(form.when, part) : null
    const others = chosen === null ? [] : part.choices.filter((choice) => choice !== chosen)
    return [others.length > 0 ? andList(others) : part.text]
  })
}

export interface WhenChoice {
  readonly label: string
  readonly set: Partial<When>
}

/** The one thing the card asks now (spec 6.6). A schedule part is answered with choice buttons, a part in words with its editor. */
export type Question =
  | { readonly kind: 'when'; readonly field: WhenField; readonly words: string; readonly choices: readonly WhenChoice[] }
  | { readonly kind: 'row'; readonly index: number; readonly words: string }
  | { readonly kind: 'days'; readonly words: string }
  | { readonly kind: 'input'; readonly agent: number; readonly input: string; readonly words: string }

const OFTEN_CHOICES: readonly WhenChoice[] = (Object.entries(OFTEN_NAMES) as [Exclude<Often, ''>, string][]).map(([often, label]) => ({ label, set: { often } }))
const DAY_CHOICES: readonly WhenChoice[] = DAY_NAMES.map((day) => ({ label: DAY_WORD(day), set: { day } }))
export const TIMES = ['08:00', '09:00', '13:00', '17:00']
const ASK_ROW: Readonly<Record<RowKind, string>> = {
  schedule: 'How often should it run?',
  look_for: 'Which tickets should it find?',
  do: 'What should it do with them?',
  where: 'Where should the result go?',
}
export const ASK_DAYS = 'Your words don’t say how many days. Change which tickets it finds to say.'

function clashQuestion(form: Form, reason: PartReason, field: WhenField): Question | null {
  const part = form.marked.find((one) => one.mark === 'cant' && one.reason === reason)
  const choices = (part?.choices ?? []).flatMap((choice): WhenChoice[] => {
    const set = clashSet(reason, choice)
    if (set === null) return []
    const label = set.at !== undefined ? clockWords(set.at) : set.day ? DAY_WORD(set.day) : set.often ? OFTEN_NAMES[set.often] : choice
    return [{ label, set }]
  })
  return choices.length >= 2 ? { kind: 'when', field, words: `${orList(choices.map((choice) => choice.label))}?`, choices } : null
}

function timeQuestion(form: Form): Question {
  const hour = bareHour(form.rows.find((row) => row.kind === 'schedule')?.text || form.text)
  const times = hour === null ? TIMES : hourChoices(hour)
  const choices = times.map((at) => ({ label: clockWords(at), set: { at } }))
  return { kind: 'when', field: 'at', words: hour === null ? 'What time should it run?' : `At ${orList(choices.map((choice) => choice.label))}?`, choices }
}

function inputQuestion(form: Form, plan: PlanView | null, first: boolean): Question | null {
  if (plan?.kind !== 'agents') return null
  for (const agent of plan.agents)
    for (const input of agent.inputs) {
      if ((input.kind === 'jira_project') !== first || valueProblem(input.kind, valueOf(form, agent, input.name)) === null) continue
      const words = input.kind === 'jira_project' ? 'Which Jira project should it use?' : input.kind === 'github_repo' ? 'Which GitHub repository should it read?' : `What should the ${lowerFirst(input.name)} be?`
      return { kind: 'input', agent: agent.index, input: input.name, words }
    }
  return null
}

function rowQuestion(form: Form, kind: RowKind): Question | null {
  const index = form.rows.findIndex((row) => row.kind === kind && row.state === 'missing')
  return index < 0 ? null : { kind: 'row', index, words: ASK_ROW[kind] }
}

/**
 * The one question to ask now, in the spec’s order: how often, the day of a weekly run, the time, which tickets, the Jira
 * project, then what it does. Two days or two times from the runtime ask which one, and a bare hour asks morning or evening.
 * Null when nothing is left to ask. What the footer counts still comes from setupLeft.
 */
export function nextQuestion(form: Form, plan: PlanView | null): Question | null {
  const { often, day } = form.when
  if (often === '') return clashQuestion(form, 'one_frequency', 'often') ?? { kind: 'when', field: 'often', words: 'How often should it run?', choices: OFTEN_CHOICES }
  if (often === 'week' && day === '') return clashQuestion(form, 'one_day', 'day') ?? { kind: 'when', field: 'day', words: 'Which day should it run?', choices: DAY_CHOICES }
  if (whenProblems(form.when).at !== undefined) return clashQuestion(form, 'one_time', 'at') ?? timeQuestion(form)
  return (
    rowQuestion(form, 'look_for') ??
    (form.marked.some((part) => part.reason === 'how_many_days') ? { kind: 'days', words: ASK_DAYS } : null) ??
    inputQuestion(form, plan, true) ??
    rowQuestion(form, 'do') ??
    rowQuestion(form, 'where') ??
    inputQuestion(form, plan, false)
  )
}

export const answerWhen = (form: Form, set: Partial<When>): Form => ({ ...form, when: { ...form.when, ...set } })

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
    left_out: leftOutOf(form),
    on: false,
  }
}

function notSavedYet(agent: PlanAgent): never {
  throw new Error(`${agent.name} is a drafted agent that has not been saved yet.`)
}

const shapeOf = (card: CardDefinition | CardView) =>
  JSON.stringify([
    card.name,
    card.purpose,
    card.good_for ?? [],
    (card.inputs ?? []).map(({ name, kind, what, example }) => [name, kind, what, example]),
    (card.blocks ?? []).map(({ say, tool }) => [say, tool ?? null]),
  ])

export function savedCopyOf(cards: readonly CardView[], owner: string, card: CardDefinition): string | null {
  const shape = shapeOf(card)
  return cards.find((saved) => saved.owner === owner && !saved.starter && shapeOf(saved) === shape)?.card_id ?? null
}

/** The drafted agents the Operator already saved with the same shape, which Turn it on reuses rather than saving again. Null until the agent list and who is signed in are read. */
export function reusedAgents(plan: PlanView | null, cards: readonly CardView[] | undefined, owner: string | undefined): ReadonlySet<number> | null {
  if (cards === undefined || owner === undefined) return null
  if (plan?.kind !== 'agents') return new Set()
  return new Set(plan.agents.flatMap((agent) => (agent.card.kind === 'drafted' && savedCopyOf(cards, owner, agent.card.definition) !== null ? [agent.index] : [])))
}

export interface SetUpCalls {
  readonly savedCard: (card: CardDefinition) => Promise<string | null>
  readonly saveCard: (card: CardDefinition) => Promise<string>
  readonly create: (body: CreateAgentUseCase) => Promise<UseCaseCreated>
  readonly deleteDraft: (draftId: string) => Promise<unknown>
}

export interface SetUpDone {
  readonly useCaseId: string
  readonly draftKept: boolean
}

/**
 * Set up: saves each drafted agent once, then the workflow as a draft that isn't on yet (ADR 0044), then drops the card's saved
 * draft, since the workflow now holds what it said. A failure keeps the agents it saved, so the next press reuses them.
 */
export async function setUp(form: Form, plan: PlanView, draftId: string | null, cards: Map<string, string>, calls: SetUpCalls): Promise<SetUpDone> {
  const task = taskWithoutSchedule(form.rows)
  const saved: Record<number, string> = {}
  for (const agent of plan.kind === 'agents' ? plan.agents : []) {
    if (agent.card.kind === 'saved') continue
    const key = `${task}#${String(agent.index)}`
    const id = cards.get(key) ?? (await calls.savedCard(agent.card.definition)) ?? (await calls.saveCard(agent.card.definition))
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

const unchecked = (row: Row): Row => (row.state === 'checking' ? { ...row, state: 'cant_do', note: NOT_CHECKED } : row)

export function draftContent(form: Form, plan: Planned | null): DraftView['content'] {
  const name = form.name.trim() || (plan ? defaultName(planView(plan.answer, form.rows)) : '') || excerpt(form.text)
  return { name: name || null, form: { ...form, rows: form.rows.map(unchecked) }, plan }
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const isString = (value: unknown): value is string => typeof value === 'string'
const STEPS: readonly unknown[] = [1, 2, 3, 4]
const ROW_STATES: readonly unknown[] = ['understood', 'changed', 'missing', 'cant_do', 'edited']
const OFTEN: readonly unknown[] = ['', 'every_day', 'weekdays', 'week']
const MARKS: readonly unknown[] = ['will_do', 'cant', 'question']
const REASONS: readonly unknown[] = [
  'not_followed',
  'cant_do',
  'ask_on_its_own',
  'one_day',
  'one_time',
  'one_frequency',
  'own_time',
  'skip_approval',
  'with_a_yes',
  'needs_the_rest',
  'how_many_days',
]

function isPart(value: unknown): value is PartView {
  return (
    isRecord(value) &&
    isString(value['text']) &&
    MARKS.includes(value['mark']) &&
    (value['reason'] === null || REASONS.includes(value['reason'])) &&
    (value['note'] === null || isString(value['note'])) &&
    Array.isArray(value['choices']) &&
    value['choices'].every(isString)
  )
}

/** The marked parts a saved draft kept. A draft saved before parts were kept has none. */
const markedIn = (form: Record<string, unknown>): PartView[] => (Array.isArray(form['marked']) ? form['marked'].filter(isPart) : [])

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

/** A part changed by you goes back to the Planner when a draft reopens, since a draft saved before every part was checked holds unchecked ones. Step 2 waits for the answer. */
function checkedAgain(form: Form): Form {
  if (!form.rows.some((row) => row.state === 'edited')) return form
  const rows = form.rows.map((row): Row => (row.state === 'edited' ? { ...row, state: 'checking', note: null } : row))
  return { ...form, rows, step: form.step > 2 ? 2 : form.step }
}

/** What still stops a saved card, from the draft as it was saved. Null when the draft holds no card. */
export function savedLeft(draft: DraftView): Left | null {
  const { form, plan } = restoreDraft(draft, false)
  if (form.rows.length === 0) return null
  return setupLeft(form, plan ? planView(plan.answer, form.rows) : null)
}

export function restoreDraft(draft: DraftView, recheck = true): { readonly form: Form; readonly plan: Planned | null } {
  const { form, plan, text, intent } = draft.content as Record<string, unknown>
  const carriedOn = isRecord(form) && form['carriedOn'] === true
  if (isForm(form)) {
    const kept = { ...form, carriedOn, marked: markedIn(form as unknown as Record<string, unknown>) }
    return { form: recheck ? checkedAgain(kept) : kept, plan: isPlanned(plan) ? plan : null }
  }
  const task = isString(text) ? text : isString(intent) ? intent : ''
  return { form: { ...EMPTY_FORM, text: task }, plan: null }
}

const LEFT_NAME: Record<RowKind, string> = {
  schedule: 'when it runs',
  look_for: 'what to look for',
  do: 'what it does',
  where: 'where it goes',
}
const LEFT_CANT = 'a part I can’t do yet'
const LEFT_CHECKING = 'my check of your new words'
const LEFT_WHEN = 'when it runs'
const LEFT_PLAN = 'the Planner to choose the agents'
const LEFT_DAYS = 'how many days'

function leftOfRow(row: Row): string | null {
  if (row.state === 'missing') return LEFT_NAME[row.kind]
  if (row.state === 'cant_do') return LEFT_CANT
  return row.state === 'checking' ? LEFT_CHECKING : null
}

/** What stops the plan from being asked for. The schedule is not one of them: the When section holds it, and the plan does not depend on it. */
export const cardBlockers = (rows: readonly Row[]): Blocker[] => rowBlockers(rows.filter((row) => row.kind !== 'schedule'))

export interface Left {
  /** What still stops Turn it on, in plain words. */
  readonly choices: readonly string[]
  /** Her own words for each part with a cross, which the workflow is set up without. */
  readonly leftOut: readonly string[]
}

/**
 * What still stops Turn it on, and what it would be set up without. The card’s footer, its button, what Turn it on sends and
 * a draft’s line on Workflows all read this, so no two places count differently. A time is never guessed: no time is something left.
 */
export function setupLeft(form: Form, plan: PlanView | null): Left {
  return { choices: choicesLeft(form, plan), leftOut: leftOutOf(form) }
}

function choicesLeft(form: Form, plan: PlanView | null): string[] {
  const left: string[] = []
  const add = (words: string | null) => {
    if (words !== null && !left.includes(words)) left.push(words)
  }
  for (const row of form.rows) if (row.kind !== 'schedule') add(leftOfRow(row))
  if (Object.keys(whenProblems(form.when)).length > 0) add(LEFT_WHEN)
  if (form.marked.some((part) => part.reason === 'how_many_days')) add(LEFT_DAYS)
  if (cardBlockers(form.rows).length > 0) return left
  if (plan === null) add(LEFT_PLAN)
  else if (plan.kind === 'cannot') add(LEFT_REQUEST)
  else if (plan.kind === 'trouble') add('the Planner to answer')
  else {
    if (plan.problems.length > 0) add(LEFT_FIX)
    if (plan.notIncluded.length > 0) add(LEFT_TOOL)
    for (const agent of plan.agents)
      for (const input of agent.inputs) if (valueProblem(input.kind, valueOf(form, agent, input.name)) !== null) add(`the ${lowerFirst(input.name)}`)
  }
  return left
}

export const andList = (items: readonly string[]): string =>
  items.length <= 2 ? items.join(' and ') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1] ?? ''}`

export const orList = (items: readonly string[]): string =>
  items.length <= 2 ? items.join(' or ') : `${items.slice(0, -1).join(', ')} or ${items[items.length - 1] ?? ''}`

export const crossedWords = (count: number): string => (count === 1 ? 'The part with a cross is left out.' : `The ${count} parts with a cross are left out.`)

const LEFT_REQUEST = 'a request I can do'
const LEFT_FIX = 'a fix for the new agent’s problems'
const LEFT_TOOL = 'nothing left out for want of a tool'
const QUESTIONS: ReadonlySet<string> = new Set([...Object.values(LEFT_NAME), LEFT_WHEN, LEFT_DAYS])


/** What else holds Set up, in the words that say what to do about it. */
const NOT_QUESTIONS: Readonly<Record<string, string>> = {
  [LEFT_CANT]: 'Change the part I can’t do yet, or leave it out.',
  [LEFT_CHECKING]: 'Checking your new words…',
  [LEFT_PLAN]: 'Waiting for the Planner…',
  'the Planner to answer': 'Waiting for the Planner…',
  [LEFT_REQUEST]: 'Change your words to something I can do.',
  [LEFT_FIX]: 'The new agent has a problem. Change your words to fix it.',
  [LEFT_TOOL]: 'Part of it needs a tool I don’t have. Change your words to leave it out.',
}

/** What the card asks her as a question, one at a time: a part not said, when it runs, how many days, or a value an agent needs ("the Jira project"). */
export const isQuestion = (choice: string): boolean => QUESTIONS.has(choice) || (/^the /.test(choice) && NOT_QUESTIONS[choice] === undefined)

/**
 * The footer’s line, in the sketch’s words: how many questions are left for her, else what else holds Set up. The rows show which,
 * one question at a time, and a cross is on the card, so nothing left says nothing: the button says what it sets up.
 */
export function leftWords({ choices }: Left): string {
  const asks = choices.filter(isQuestion).length
  if (asks > 0) return asks === 1 ? '1 question to answer' : `${String(asks)} questions to answer`
  const other = choices[0]
  return other === undefined ? '' : (NOT_QUESTIONS[other] ?? '')
}

/** “Set up the part I can” while any part has a cross, so the button never claims the whole request. */
export const setUpWords = (left: Left): string => (left.leftOut.length > 0 ? 'Set up the part I can' : 'Set up')

/** Resume reopens the card on Home, where the draft's id sits in the address. */
export const draftPath = (draftId: string) => `/?draft=${encodeURIComponent(draftId)}`

export const CARD_STEP: Step = 2

/** The clause of the typed request that holds the words, cut at a comma or a full stop. */
function clauseOf(text: string, words: string): string {
  const at = text.toLowerCase().indexOf(words.toLowerCase())
  if (at < 0 || words === '') return ''
  const start = text.slice(0, at).search(/[^,.;!?]*$/)
  const end = text.slice(at).search(/[,.;!?]/)
  return text.slice(start, end < 0 ? text.length : at + end)
}

const UNSET: Readonly<Partial<Record<PartReason, Partial<When>>>> = { one_frequency: { often: '', day: '' }, one_day: { often: 'week', day: '' }, one_time: { at: '' } }

/**
 * The schedule from her words. A clash leaves its schedule row empty, so the rest of that clause is read instead, with the
 * clashing day, time or frequency left for her to choose. Nothing is ever picked for her.
 */
function whenFrom(said: string, typed: string, marked: readonly PartView[]): When {
  const clashes = marked.filter(isClash)
  const first = clashes[0]
  if (first === undefined) return readWhen(said)
  const read = readWhen(clauseOf(typed, first.text))
  return clashes.reduce<When>((when, part) => ({ ...when, ...(part.reason ? UNSET[part.reason] : {}) }), { ...read, filledFrom: said })
}

/** A set-up card’s starting state from the Planner’s rows and parts. The schedule is read from her words only, so a time is never guessed. */
export function cardFrom(
  name: string,
  rows: readonly { readonly kind: RowKind; readonly text: string; readonly state: RowState; readonly note: string | null }[],
  typed: string,
  parts: readonly PartView[] = [],
): Form {
  const kept = rows.filter((row) => row.state !== 'cant_do')
  const said = kept.find((row) => row.kind === 'schedule')?.text ?? ''
  const marked = parts.filter((part) => part.mark !== 'will_do')
  return {
    ...EMPTY_FORM,
    step: CARD_STEP,
    text: typed,
    name: name.trim(),
    rows: kept.map((row) => ({ kind: row.kind, text: row.text, state: row.state, note: row.note, planner: null })),
    when: whenFrom(said, typed, marked),
    marked,
  }
}

export interface PartResult {
  readonly state: 'fits' | 'cant_do'
  readonly note?: string
}

/** The Planner’s check of one changed part. Anything but a clear “fits”, including no answer, leaves the part as one I can’t do. */
export function afterPartCheck(form: Form, part: Part, result: PartResult | null): Form {
  const why = result === null ? NOT_CHECKED : result.state === 'fits' ? null : (result.note ?? CANT_YET)
  const rows = form.rows.map((row): Row =>
    row.state === 'checking' && row.kind === part.kind && row.text === part.text ? { ...row, state: why === null ? 'edited' : 'cant_do', note: why } : row,
  )
  return { ...form, rows }
}

/** The person’s own words for a time, shown in the sentence and in When. Empty until the three fields hold a real time. */
export function whenSaid(when: When): string | null {
  return Object.keys(whenProblems(when)).length === 0 ? whenWords(when) : null
}

export const DEST_WORDS = 'one new Jira ticket'

/** Where a set-up card is: open to change, being set up, built as a draft that builds and tests, or dropped. */
export type CardPhase =
  | { readonly kind: 'open' }
  | { readonly kind: 'creating' }
  | { readonly kind: 'built'; readonly useCaseId: string; readonly draftKept: boolean; readonly newAgents: readonly string[] }
  | { readonly kind: 'dropped' }

export type CardPress =
  | { readonly type: 'set_up' }
  | { readonly type: 'built'; readonly useCaseId: string; readonly draftKept: boolean; readonly newAgents: readonly string[] }
  | { readonly type: 'refused' }
  | { readonly type: 'never_mind' }
  | { readonly type: 'undo' }

/** What a press does to the card. Only an open card sets up or drops, and only a card being set up is built or opened again. */
export function cardPhase(phase: CardPhase, press: CardPress): CardPhase {
  switch (press.type) {
    case 'set_up':
      return phase.kind === 'open' ? { kind: 'creating' } : phase
    case 'built':
      return phase.kind === 'creating' ? { kind: 'built', useCaseId: press.useCaseId, draftKept: press.draftKept, newAgents: press.newAgents } : phase
    case 'refused':
      return phase.kind === 'creating' ? { kind: 'open' } : phase
    case 'never_mind':
      return phase.kind === 'open' ? { kind: 'dropped' } : phase
    case 'undo':
      return phase.kind === 'dropped' ? { kind: 'open' } : phase
  }
}
