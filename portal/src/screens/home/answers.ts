import type { CantReply, CantRowView, CapabilitiesView, CapabilityView, PartReply, PlannerReply, RowKind, SetupCardReply, UnderstoodRowView } from '../../api/types'
import { count } from '../run/words'
import type { Row } from '../workflows/workflow'

/** The words for each part of a request. They match the old New workflow's, so a person sees the same names in both. */
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

/** What the old New workflow is handed: the typed words for a request it can read whole, the card’s own words for an alternative. */
export function setupTask(reply: SetupCardReply | PartReply | CantReply, typed: string): string {
  if (reply.answer === 'cant') return reply.alternative?.answer === 'setup_card' ? joinedRows(reply.alternative.rows) : typed
  return typed
}

function joinedRows(rows: readonly UnderstoodRowView[]): string {
  return rows
    .filter((row) => row.state !== 'cant_do' && row.text.trim() !== '')
    .map((row) => row.text.replace(/[.!?]+$/, ''))
    .join('. ')
}

export const SAY = {
  setup_card: 'Here’s what I understood. I filled in what I could.',
  part: 'I can do part of that. Here is the part I can do, and the part I can’t do yet.',
  cant: 'I can’t do that yet.',
  cantWithAlternative: 'I can’t do all of that, but I can set up something close.',
  which_software: 'Which software should I watch?',
  refused: 'I can’t set that up. Anything that changes data waits for a yes, every time.',
  abilities: 'Here is what I can do, and what I can’t do yet.',
  ideas: 'Here are some places to start. Pick one and I’ll fill in what I can.',
  nothingNeeds: 'Nothing needs you right now.',
} as const

export const watchlistSay = (software: string | null, listed: boolean): string => {
  if (software === null) return 'That belongs on the Software watchlist, which checks the software on it for new releases.'
  return listed
    ? `${software} is already on the Software watchlist.`
    : `${software} is software, so it belongs on the Software watchlist, which checks the software on it for new releases.`
}

export const needsSay = (total: number): string => (total === 0 ? SAY.nothingNeeds : `${count(total, 'thing')} ${total === 1 ? 'needs' : 'need'} you.`)

/** The sentence for an answer the Planner reply alone decides. The three state answers are filled in from the pages’ own functions. */
export function sayOf(reply: PlannerReply): string | null {
  switch (reply.answer) {
    case 'setup_card':
      return SAY.setup_card
    case 'part':
      return SAY.part
    case 'cant':
      return reply.alternative ? SAY.cantWithAlternative : SAY.cant
    case 'watchlist':
      return watchlistSay(reply.software, reply.already_listed !== null)
    case 'which_software':
      return SAY.which_software
    case 'refused':
      return SAY.refused
    case 'abilities':
      return SAY.abilities
    case 'ideas':
      return SAY.ideas
    case 'offline':
      return reply.message
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
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

/** Check my workflows: one sentence from the same rows the Workflows list draws. */
export function workflowsSay(rows: readonly Row[]): string {
  if (rows.length === 0) return 'You have no workflows yet.'
  const stopped = rows.filter((row) => row.latest?.state === 'failed').length
  const waiting = rows.filter((row) => row.latest?.state === 'awaiting_approval').length
  const paused = rows.filter((row) => row.useCase.state === 'paused').length
  const parts = [
    stopped > 0 ? `${stopped} stopped` : null,
    waiting > 0 ? `${waiting} ${waiting === 1 ? 'is' : 'are'} waiting for a yes` : null,
    paused > 0 ? `${paused} ${paused === 1 ? 'is' : 'are'} paused` : null,
  ].filter((part) => part !== null)
  const running = rows.length - stopped - waiting - paused
  if (running > 0) parts.push(`${running} ${running === 1 ? 'is' : 'are'} running`)
  return `You have ${count(rows.length, 'workflow')}. ${parts.join(', ')}.`
}

export interface CapabilityGroups {
  readonly can: readonly CapabilityView[]
  readonly setup: readonly CapabilityView[]
  readonly notYet: readonly CapabilityView[]
}

/** The “I can” and “Not yet” lists, split by the state the platform gave each entry. */
export function capabilityGroups(view: CapabilitiesView): CapabilityGroups {
  const all = view.capabilities
  return {
    can: all.filter((entry) => entry.state === 'ready'),
    setup: all.filter((entry) => entry.state === 'needs_setup' || entry.state === 'down'),
    notYet: all.filter((entry) => entry.state === 'planned' || entry.state === 'unsupported'),
  }
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
