import type { CantRowView, CapabilitiesView, CapabilityView, OfflineReply, PauseReply, PlannerReply, QuestionReply, ResumeReply, RowKind, UnderstoodRowView } from '../../api/types'
import { count } from '../run/words'
import { isRunning, type Row } from '../workflows/workflow'
import { cantOnCard } from './parts'

/** The words for each part of a request. They match the names the removed New workflow screen used. */
export const ROW_LABEL: Readonly<Record<RowKind, string>> = {
  schedule: 'When',
  look_for: 'Looks for',
  do: 'Does',
  where: 'Where it goes',
}

export const TAG_FILLED = 'Filled in by me'
export const TAG_CHOICE = 'Needs a choice'
export const TAG_CANT = 'Can’t do this yet'

/** What a part with nothing in it says, so a chip is never blank. A time is never guessed. */
const NOT_SAID: Readonly<Record<RowKind, string>> = {
  schedule: 'No time chosen yet',
  look_for: 'Not said yet',
  do: 'Not said yet',
  where: 'Not said yet',
}

export interface CardLine {
  readonly kind: RowKind
  readonly label: string
  readonly text: string
  readonly tag: string | null
  /** What the person said and how the Planner read it, or why it can’t be done. */
  readonly note: string | null
}

/** A part the platform can’t do may come with no text of its own. Its note then stands in, so the line is never empty. */
export function lineText(row: Pick<UnderstoodRowView, 'kind' | 'text' | 'note'>): string {
  if (row.text.trim() !== '') return row.text
  if (row.note !== null && row.note.trim() !== '') return row.note
  return NOT_SAID[row.kind]
}

export function cardLines(rows: readonly UnderstoodRowView[]): CardLine[] {
  return rows.map((row) => {
    const tag = row.state === 'changed' ? TAG_FILLED : row.state === 'missing' ? TAG_CHOICE : row.state === 'cant_do' ? TAG_CANT : null
    const text = lineText(row)
    const note = row.note !== null && row.note.trim() !== '' && row.note !== text ? row.note : null
    return { kind: row.kind, label: ROW_LABEL[row.kind], text, tag, note }
  })
}

const CANT_FALLBACK = 'The platform can’t do this yet.'

export interface CantLine {
  readonly text: string
  readonly note: string
}

/** A can’t-do row with no text still shows its note, and a row with neither says so plainly. */
export function cantLine(row: Pick<CantRowView, 'text' | 'note'>): CantLine {
  const text = row.text.trim()
  const note = row.note.trim()
  if (text === '') return { text: note === '' ? CANT_FALLBACK : note, note: '' }
  return { text, note: note === text ? '' : note }
}

export const cantLines = (rows: readonly CantRowView[]): CantLine[] => rows.map(cantLine)

export const SAY = {
  setup_card: 'Here’s what I understood. I filled in what I could.',
  setupCrossed: 'Here’s what I understood. I can’t do every part of it.',
  part: 'I can do part of that. Here is the part I can do, and the part I can’t do yet.',
  cant: 'I can’t do that yet.',
  cantWithAlternative: 'I can’t do all of that, but I can set up something close.',
  which_software: 'Which software should I watch?',
  refused: 'I can’t set that up. Anything that changes data waits for a yes, every time.',
  nothingNeeds: 'Nothing needs you right now.',
} as const

/** Who is asking: an Operator sets up and changes workflows, and anyone else asks questions only (ADR 0043). */
export type Asker = 'operator' | 'approver'

/** The software a question answer offers actions on, which only an Operator gets. With some, the answer leads a card. */
export const questionActions = (reply: QuestionReply, asker: Asker): readonly string[] => (asker === 'operator' ? (reply.about_software ?? []) : [])

/**
 * Answers that are only words, drawn as a message with the Planner's name on it (the sketch's `.mb`). Every other answer leads its
 * cards with its sentence and no name (`.mcard`), a question answer with actions included.
 */
export function wordsOnly(reply: PlannerReply, asker: Asker): boolean {
  if (reply.answer === 'question') return questionActions(reply, asker).length === 0
  if (reply.answer === 'pause' || reply.answer === 'resume') return reply.choices.length === 0
  return reply.answer === 'operators' || (reply.answer === 'offline' && asker === 'approver')
}

/** The offline answer to someone who isn’t an Operator: one line, with no place to start and nothing only an Operator can do. */
const APPROVER_OFFLINE: Readonly<Record<OfflineReply['why'], string>> = {
  no_model: 'I can’t answer questions until an AI model is connected. An Operator can connect one in Settings.',
  too_slow: 'The Planner took too long to read your question. Try again in a moment.',
  trouble: 'The Planner couldn’t read your question just now. Try again in a moment.',
}

/** A pause or a resume the platform carried out, or that found the workflow already that way. */
export const switchedSay = (answer: 'pause' | 'resume', name: string, already: boolean): string => {
  if (answer === 'pause') return already ? `${name} is already paused.` : `Paused ${name}. It won’t start a new run until you resume it.`
  return already ? `${name} is already on.` : `${name} is on again.`
}

/** What pausing or resuming the Software watchlist does, beside its chip: it holds every software’s check. */
export const watchlistSwitchNote = (answer: 'pause' | 'resume'): string =>
  answer === 'pause' ? 'Pausing the Software watchlist stops the checks of every software on it.' : 'Turning the Software watchlist back on checks every software on it again.'

const withoutArticle = (words: string): string => words.replace(/^(?:the|my|our|that|this)\s+/i, '')

function switchSay(reply: PauseReply | ResumeReply): string {
  if (reply.use_case_id !== null && reply.name !== null) return switchedSay(reply.answer, reply.name, reply.already)
  if (reply.missing !== null) return `You don’t have a workflow called “${withoutArticle(reply.missing)}”.`
  return reply.choices.length > 0 ? 'Which workflow?' : 'You have no workflows yet.'
}

/** A can’t its registry entry says in one line, drawn as its own card. Any other can’t is a row on the What I can’t do yet card. */
export const oneLine = (row: CantRowView): boolean => row.needs !== null && (row.instead ?? null) !== null

export const watchlistSay = (software: string | null, listed: boolean): string => {
  if (software === null) return 'That belongs on the Software watchlist, which checks the software on it for new releases.'
  return listed
    ? `${software} is already on the Software watchlist.`
    : `${software} is software, so it belongs on the Software watchlist, which checks the software on it for new releases.`
}

/** “Set up another workflow”: the sentence counts the places to start it shows, so the words and the chips never disagree. */
export const ideasSay = (places: number): string =>
  places === 0 ? 'I have no places to start to suggest right now. Tell me what you would like.' : places === 1 ? 'Here is a place to start. Pick it, or tell me something else.' : `Here are ${places} places to start. Pick one, or tell me something else.`

export const needsSay = (total: number): string => (total === 0 ? SAY.nothingNeeds : `${count(total, 'thing')} ${total === 1 ? 'needs' : 'need'} you.`)

/**
 * The sentence for an answer the Planner reply alone decides. The state answers, the person’s decisions, the requests to decide,
 * who makes changes and the edit card are filled in from the platform as it is now.
 */
export function sayOf(reply: PlannerReply, asker: Asker = 'operator'): string | null {
  switch (reply.answer) {
    case 'setup_card':
      return reply.parts.some((part) => part.mark === 'cant') ? SAY.setupCrossed : SAY.setup_card
    case 'part':
      return SAY.part
    case 'cant':
      if (cantOnCard(reply)) return SAY.setupCrossed
      if (reply.alternative && reply.cant.every((row) => row.needs === null)) return sayOf(reply.alternative)
      if (reply.alternative) return SAY.cantWithAlternative
      return reply.cant.filter((row) => row.needs !== null).every(oneLine) ? null : SAY.cant
    case 'watchlist':
      return watchlistSay(reply.software, reply.already_listed !== null)
    case 'which_software':
      return SAY.which_software
    case 'refused':
      return SAY.refused
    case 'pause':
    case 'resume':
      return switchSay(reply)
    case 'abilities':
    case 'ideas':
      return null
    case 'offline':
      return asker === 'operator' ? reply.message : APPROVER_OFFLINE[reply.why]
    case 'question':
      return reply.text
    case 'edit':
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
    case 'operators':
    case 'decided':
    case 'decide':
      return null
  }
}

/** What a refusal can do next. The words after the unsafe part go back to the Planner, never straight to a set-up (they can ask for more). */
export interface RefusalNext {
  readonly rest: string | null
}

export function refusalNext(reply: { readonly rest: string }): RefusalNext {
  const rest = reply.rest.trim()
  return { rest: rest === '' ? null : rest }
}

export const SAY_ANOTHER_WAY = 'If you only meant that you don’t need to look at it yourself, say it another way.'

/** Check my workflows: one sentence from the same rows the Workflows list draws. Someone who isn’t an Operator reads the team’s. */
export function workflowsSay(rows: readonly Row[], asker: Asker = 'operator'): string {
  if (rows.length === 0) return asker === 'operator' ? 'You have no workflows yet.' : 'There are no workflows yet. Operators set them up.'
  const stopped = rows.filter((row) => row.useCase.last_run?.state === 'failed').length
  const waiting = rows.filter((row) => row.useCase.last_run?.state === 'awaiting_approval').length
  const paused = rows.filter((row) => row.useCase.state === 'paused').length
  // Counted from the same fact the row's Running pill reads, so the sentence never says more than the rows show.
  const running = rows.filter((row) => isRunning(row.useCase.last_run)).length
  const parts = [
    stopped > 0 ? `${stopped} stopped` : null,
    waiting > 0 ? `${waiting} ${waiting === 1 ? 'is' : 'are'} waiting for a yes` : null,
    paused > 0 ? `${paused} ${paused === 1 ? 'is' : 'are'} paused` : null,
    running > 0 ? `${running} ${running === 1 ? 'is' : 'are'} running` : null,
  ].filter((part) => part !== null)
  return `${asker === 'operator' ? 'You have' : 'The team has'} ${count(rows.length, 'workflow')}. ${parts.length > 0 ? `${parts.join(', ')}.` : 'None needs you.'}`
}

export interface CapabilityGroups {
  readonly can: readonly CapabilityView[]
  readonly setup: readonly CapabilityView[]
}

/**
 * The lists Home shows without being asked, split by the state the platform gave each entry. They hold only what software
 * versioning uses (the registry's `focus` mark). A request for anything else is answered when it is asked, with the can't.
 */
export function capabilityGroups(view: CapabilitiesView): CapabilityGroups {
  const all = view.capabilities.filter((entry) => entry.focus)
  return {
    can: all.filter((entry) => entry.state === 'ready'),
    setup: all.filter((entry) => entry.state === 'needs_setup' || entry.state === 'down'),
  }
}

export interface CapabilityLine extends CapabilityView {
  readonly short: string
}

export interface CapabilityCard {
  readonly can: readonly CapabilityLine[]
  readonly notYet: readonly string[]
}

/** The chat’s What I can do card, from the registry’s short words: the entries built, with their state, and the names of those that aren’t. */
export function capabilityCard(view: CapabilitiesView): CapabilityCard {
  const named = view.capabilities.filter((entry): entry is CapabilityLine => entry.short !== null)
  const built = (entry: CapabilityLine) => entry.state !== 'planned' && entry.state !== 'unsupported'
  return { can: named.filter(built), notYet: named.filter((entry) => !built(entry)).map((entry) => entry.short) }
}

export function stateWords(entry: Pick<CapabilityView, 'state'>): string | null {
  switch (entry.state) {
    case 'ready':
      return null
    case 'needs_setup':
      return 'Needs setup'
    case 'down':
      return 'Not answering right now'
    case 'planned':
      return 'Planned'
    case 'unsupported':
      return 'Not on the team’s plan'
  }
}

/** Why an entry is not ready, in the platform’s words. */
export function whyNot(entry: Pick<CapabilityView, 'cant' | 'why' | 'fix'>): string {
  return [entry.why, entry.fix].filter((part): part is string => part !== null && part.trim() !== '').join(' ')
}

/** The starting points “Set up another workflow” offers: the platform’s examples that set something up, which it already vouches for. */
export function startingPoints(view: CapabilitiesView): readonly string[] {
  return view.examples.filter((example) => example.kind !== 'learn').map((example) => example.text)
}
