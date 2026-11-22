import type { CantRowView, CapabilitiesView, CapabilityView, OfflineReply, PartView, PauseReply, PlannerReply, QuestionReply, RemoveSoftwareReply, ResumeReply, RowKind, ScheduleView, UnderstoodRowView, UseCaseView, WatchlistView } from '../../api/types'
import { andList, count, type NameOf } from '../run/words'
import { checksOnItsOwn, heldWords as heldScheduleWords, PAUSED_WORDS, repeatWords } from '../software/software'
import { scheduleZoneName } from '../workflows/times'
import { isRunning, lastRunLine, lifeWords, nextRunWords, type Row } from '../workflows/workflow'
import { lowerFirst, readWhen, scheduleOf } from './card'
import { sayChanged } from './changed'
import { cantOnCard, crossWords, quote, watchlistRuns } from './parts'

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
  setup_card: 'Here’s what I understood.',
  setupCrossed: 'Here’s what I understood.',
  alreadyHave: 'You already have this one.',
  part: 'Here’s what I understood.',
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
  if (reply.answer === 'n8n') return true
  // A draft with its card leads the card. Only a refusal is words.
  if (reply.answer === 'draft_started') return reply.drafted_id === null
  if (reply.answer === 'remove_software') return reply.matches.length === 0
  // A free reply is the Planner's own words, with its chips or button under them inside the same message.
  return reply.answer === 'reply' || reply.answer === 'operators' || (reply.answer === 'offline' && asker === 'approver')
}

/** Who fronts an answer: the AI troubleshooter owns the run card, and the Planner every other answer. */
export const whoOf = (reply: PlannerReply): 'planner' | 'troubleshooter' => (reply.answer === 'why_stopped' ? 'troubleshooter' : 'planner')

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

/** When the Software watchlist checks, as its page says it: "every Monday at 9:00", with the zone when it is not the team's. */
export const watchlistRunsWords = (schedule: ScheduleView): string => {
  const zone = scheduleZoneName(schedule.time_zone)
  return `${repeatWords(schedule)}${zone ? ` ${zone}` : ''}`
}

/** A time of their own in the schedule words ("every day at 9:00"), or in their own words when they don't name both how often and when. */
export function askedRunsWords(said: string): string {
  const when = readWhen(said)
  return when.often !== '' && when.at !== '' ? repeatWords(scheduleOf(when)) : lowerFirst(said.trim())
}

/** A watched software's card beside a time of its own: the Software watchlist checks every software it holds on its one schedule. */
export const ownTimeSay = (count: number, runs: string): string => `The watchlist checks all ${count} software ${runs}, not each one on its own.`

/** The main button beside it, which asks the Planner to move the whole watchlist to the time they asked. */
export const moveAllLabel = (count: number, asked: string): string => `Check all ${count} ${asked}`

/** Why the Software watchlist starts no check now, in its page's words: paused, or its schedule held. Null while it checks on its own or has no schedule. */
export function notCheckingWords(view: Pick<WatchlistView, 'state' | 'schedule'>): string | null {
  if (view.state === 'paused') return PAUSED_WORDS
  return view.schedule ? heldScheduleWords(view.schedule) : null
}

export interface OwnTimeOffer {
  /** What the card says of the watchlist's one schedule, then why it starts no check now, when it doesn't. */
  readonly says: readonly string[]
  readonly label: string
  /** The old offer's request, which the Planner answers with the change card, so nothing changes until they save it. */
  readonly request: string
  /** Not while the watchlist is paused or held, when moving its time alone starts no check. */
  readonly main: boolean
}

/**
 * A watched software's card beside a time of its own. While the watchlist checks on its own and holds more than one software, the
 * approved words name its schedule and the move. Otherwise the cross's own words stay, naming the schedule only while it runs.
 */
export function ownTimeOffer(ownTime: PartView, view: WatchlistView | null | undefined): OwnTimeOffer {
  const request = watchlistRuns(ownTime.text)
  const runs = checksOnItsOwn(view) ? (view?.schedule ?? null) : null
  const total = view?.software.length ?? 0
  if (runs && total > 1) return { says: [ownTimeSay(total, watchlistRunsWords(runs))], label: moveAllLabel(total, askedRunsWords(ownTime.text)), request, main: true }
  const stopped = view ? notCheckingWords(view) : null
  const line = crossWords(ownTime, { watchlist: runs })
  return { says: stopped === null ? [line] : [line, stopped], label: request, request, main: stopped === null }
}

/** The Planner's release words, as its `RELEASE_ROOTS`: a request with one asks about the version or the releases. */
const VERSION_WORD = /\b(?:versions?|releas(?:e|es|ed|ing)|upgrad(?:e|es|ed|ing)|patch(?:es|ed|ing)?)\b/i

/**
 * The software card's line for software the watchlist doesn't hold. Why the version they run isn't known fits only a question about
 * the version. Asked to add, watch or keep track of it, it isn't on the watchlist yet, and that is all.
 */
export const unwatchedSay = (word: string): string => (VERSION_WORD.test(word) ? 'It isn’t on the watchlist, so I don’t know which version you run.' : 'It isn’t on the watchlist yet.')

/** The most names a sentence lists before it counts the rest. */
const NAMED = 8

/** What the Watchlist holds, for a name it doesn’t hold. */
function heldWords(names: readonly string[]): string {
  if (names.length === 0) return 'Your Watchlist is empty.'
  if (names.length <= NAMED) return `It holds ${andList(names)}.`
  return `It holds ${names.slice(0, NAMED).join(', ')} and ${names.length - NAMED} more.`
}

/** Software to take off the Watchlist: the one match, a choice of several, or what it holds when the name isn’t on it. */
export function removeSay(reply: RemoveSoftwareReply): string {
  const [only, ...others] = reply.matches
  if (only === undefined) return `${reply.software} isn’t on your Watchlist. ${heldWords(reply.watched)}`
  if (others.length > 0) return `More than one software on your Watchlist could be ${reply.software}. Which one should I remove?`
  return `Remove ${only.name} from the Watchlist? It won’t be checked any more.`
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
      if (reply.similar) return SAY.alreadyHave
      return reply.parts.some((part) => part.mark === 'cant') ? SAY.setupCrossed : SAY.setup_card
    case 'part':
      return SAY.part
    case 'cant':
      if (cantOnCard(reply)) return SAY.setupCrossed
      // “Something close” only leads a card that sets something up. A watch offer leads with its own sentence.
      if (reply.alternative && (reply.alternative.answer === 'watchlist' || reply.cant.every((row) => row.needs === null))) return sayOf(reply.alternative)
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
    case 'remove_software':
      return removeSay(reply)
    case 'explain':
    case 'abilities':
    case 'ideas':
    case 'didnt_follow':
      return null
    case 'offline':
      return asker === 'operator' ? reply.message : APPROVER_OFFLINE[reply.why]
    case 'question':
    case 'reply':
      return reply.text
    case 'changed_in_n8n':
      return sayChanged(reply)
    case 'n8n':
      return reply.said
    case 'draft_started':
      return reply.drafted_id === null ? (reply.refused ?? 'I couldn’t start that draft.') : null
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

/** The button that sends a free reply’s offer. It says the request itself, so what they tap is exactly what is sent. */
export const offerLabel = (request: string): string => `Try ${quote(request.trim())}`

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

/**
 * Check my workflows when there is one workflow: whether it is on, how its last run went in its row’s own words, and its next run
 * in the panel’s own Next run words, so a held schedule or a refused move says Not running there too. Paused says it once. Its name
 * is quoted, so it reads as a name and never as the Planner’s words.
 */
export function oneWorkflowSay(useCase: UseCaseView, now: Date, nameOf: NameOf): string {
  const life = useCase.state === 'draft' ? 'a draft' : lifeWords(useCase.state).toLowerCase()
  const last = lastRunLine(useCase, now, nameOf)
  const ran = useCase.last_run ? `${last.charAt(0).toUpperCase()}${last.slice(1).replace(/[.!?]+$/, '')}.` : 'It hasn’t run yet.'
  const next = useCase.state === 'paused' ? '' : ` Next run: ${nextRunWords(useCase, now)}.`
  return `${quote(useCase.name)} is ${life}. ${ran}${next}`
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

/** What How to start says first, so a question about what the app is for gets that answer before the steps. */
export const START_LEAD = 'This app runs repetitive work for you. Tell me the task and I’ll draft it. Nothing is written without an Approver’s yes.'

/** How to start, step by step: the registry’s first example in their words, and Teams named only while the platform can ask for a yes there. */
export function startSteps(view: CapabilitiesView): readonly string[] {
  const example = startingPoints(view)[0]
  const teams = view.capabilities.some((entry) => entry.id === 'teams.ask' && entry.state === 'ready')
  return [
    example === undefined ? 'Tell me what should run by itself, in your own words.' : `Tell me what should run by itself, in your own words, like “${example}”.`,
    'Check the card I make, and change anything I guessed.',
    'Press Turn on. I do a test run, which writes nothing, and turn it on if the test passes.',
    teams ? 'Nothing is written until an Approver says yes in Teams.' : 'Nothing is written until an Approver says yes.',
  ]
}
