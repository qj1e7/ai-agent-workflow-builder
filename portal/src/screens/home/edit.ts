import type { Day, EditChoice, EditReply, PartView, UseCaseView, VersionView } from '../../api/types'
import { clockWords, everyWords, repeatWords } from '../software/software'
import { undoneWords } from '../workflows/workflow'
import { hourChoices, orList, TIMES } from './card'
import { howOftenWords } from './parts'

/** A schedule the edit card shows or saves: a day and a time, in Singapore. */
export interface Schedule {
  readonly day: Day
  readonly at: string
}

/** What she picked on the card: one of the workflows it offered, a day, a time. A pick only fills what the Planner left open. */
export interface Picks {
  readonly useCaseId: string | null
  readonly day: Day | null
  readonly at: string | null
}

export interface Choice {
  readonly label: string
  readonly value: string
}

/** The one thing the card asks before Save, in the spec's order: the day of a weekly run, then the time. */
export interface Question {
  readonly field: 'day' | 'at'
  readonly words: string
  readonly choices: readonly Choice[]
  /** The time question offers Another time, unless the hour was said and only morning or evening is left. */
  readonly another: boolean
}

/**
 * What an edit answer is, from the reply and her picks. Each kind is one answer of spec 6.7, so the card draws one state and
 * never two that disagree.
 */
export type EditView =
  | { readonly kind: 'missing'; readonly words: string; readonly software: string | null }
  | { readonly kind: 'which'; readonly choices: readonly EditChoice[] }
  | { readonly kind: 'cant'; readonly target: EditChoice | null; readonly cant: NonNullable<EditReply['cant']> }
  | { readonly kind: 'same'; readonly target: EditChoice; readonly before: Schedule }
  | { readonly kind: 'held'; readonly target: EditChoice }
  | { readonly kind: 'stale'; readonly target: EditChoice; readonly now: Schedule | null }
  | { readonly kind: 'ask'; readonly target: EditChoice; readonly question: Question }
  | { readonly kind: 'ready'; readonly target: EditChoice; readonly after: Schedule }

/** What she has done with the card. Saved and undone keep the schedule as it was saved, so the card reads the same later. */
export type Phase =
  | { readonly kind: 'open' }
  | { readonly kind: 'kept' }
  | { readonly kind: 'saved'; readonly target: EditChoice; readonly after: Schedule; readonly version: number | null }
  | { readonly kind: 'undone'; readonly target: EditChoice; readonly after: Schedule; readonly version: number }

export const NO_PICKS: Picks = { useCaseId: null, day: null, at: null }

const WEEKDAYS: readonly Day[] = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const dayName = (day: Day): string => everyWords(day).replace(/^every /, '')
const upperFirst = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1)

/** "Every weekday at 8:00", as the card's Before and After say it. */
export const scheduleText = (schedule: Schedule): string => upperFirst(repeatWords(schedule))

/** The workflow the reply names, or the one she picked from its choices. */
export function targetOf(reply: EditReply, picks: Picks): EditChoice | null {
  if (reply.use_case_id !== null && reply.name !== null) {
    return { use_case_id: reply.use_case_id, name: reply.name, watchlist: reply.watchlist, before: reply.before, after: reply.after }
  }
  return reply.choices.find((choice) => choice.use_case_id === picks.useCaseId) ?? null
}

const IT = /\b(?:it|this one|that one)\b/i

/** "make it daily" means the workflow just talked about, when it is one of the choices. Words that fit several never pick one. */
export function firstPicks(reply: EditReply, about: string | null, typed: string): Picks {
  const named = about !== null && IT.test(typed) && reply.choices.some((choice) => choice.use_case_id === about)
  return { ...NO_PICKS, useCaseId: named ? about : null }
}

const sameSchedule = (a: Schedule | null, b: Schedule | null): boolean => (a === null || b === null ? a === b : a.day === b.day && a.at === b.at)

function timeQuestion(hour: number | null): Question {
  if (hour !== null) {
    const times = hourChoices(hour)
    const choices = times.map((at) => ({ label: clockWords(at), value: at }))
    return { field: 'at', words: `At ${orList(choices.map((choice) => choice.label))}?`, choices, another: false }
  }
  return { field: 'at', words: 'What time should it run?', choices: TIMES.map((at) => ({ label: clockWords(at), value: at })), another: true }
}

const DAY_QUESTION: Question = {
  field: 'day',
  words: 'Which day should it run?',
  choices: WEEKDAYS.map((day) => ({ label: upperFirst(dayName(day)), value: day })),
  another: false,
}

/**
 * `now` is the workflow's schedule as the platform holds it, or undefined while it is read. A card whose Before is no longer
 * true would save an After worked out from the old schedule, so it asks to be asked again instead.
 */
export function editView(reply: EditReply, picks: Picks, now?: Schedule | null): EditView {
  const target = targetOf(reply, picks)
  if (reply.cant !== null) return { kind: 'cant', target, cant: reply.cant }
  if (target === null) return reply.missing !== null ? { kind: 'missing', words: reply.missing, software: reply.software } : { kind: 'which', choices: reply.choices }
  if (reply.holds_save || target.after === null) return { kind: 'held', target }
  if (now !== undefined && !sameSchedule(now, target.before)) return { kind: 'stale', target, now }
  const day = target.after.day ?? picks.day
  const at = target.after.at ?? picks.at
  if (day === null) return { kind: 'ask', target, question: DAY_QUESTION }
  if (at === null) return { kind: 'ask', target, question: timeQuestion(reply.hour) }
  const after = { day, at }
  if (target.before !== null && target.before.day === day && target.before.at === at) return { kind: 'same', target, before: target.before }
  return { kind: 'ready', target, after }
}

/** The parts the card marks: every cross and question. A change it can't make is said in the sentence, so its own cross isn't drawn twice. */
export function crossesOf(reply: EditReply, view: EditView): PartView[] {
  return reply.parts.filter((part) => part.mark !== 'will_do' && !(view.kind === 'cant' && part.reason === view.cant))
}

const withoutArticle = (words: string): string => words.replace(/^(?:the|my|our|that|this)\s+/i, '')

/** The sentence while the card is open. `every` is the Software watchlist's day, for a check of software it doesn't watch. */
export function openSay(reply: EditReply, view: EditView, every: Day | null): string {
  switch (view.kind) {
    case 'missing':
      if (view.software === null) return `You don’t have a workflow called “${withoutArticle(view.words)}”.`
      return `You don’t have a ${view.software} check. ${view.software} isn’t on the Software watchlist${every ? `, which checks software ${everyWords(every)}` : ''}.`
    case 'which':
      return view.choices.length > 0 ? 'Which workflow should I change?' : 'You have no workflows to change yet.'
    case 'cant':
      if (view.cant === 'how_often') return howOftenWords(reply.parts.find((part) => part.reason === 'how_often')?.text ?? '')
      return `From the chat I can only change when ${view.target?.name ?? 'a workflow'} runs.`
    case 'same': {
      const now = repeatWords(view.before)
      return view.target.watchlist && reply.software ? `${reply.software} is checked with all your software, which already runs ${now}.` : `${view.target.name} already runs ${now}.`
    }
    case 'stale':
      return `${view.target.name} changed since I read it, and ${view.now ? `runs ${repeatWords(view.now)}` : 'has no schedule'} now. Ask again to change it.`
    case 'held':
      if (crossesOf(reply, view).length === 0) return 'I couldn’t tell when it should run. Ask again with the day or the time.'
      return `${view.target.watchlist && reply.software ? `${reply.software} is checked with all your software. ` : ''}Here’s the change, but I can’t do every part of it.`
    case 'ask':
    case 'ready': {
      const software = view.target.watchlist && reply.software ? `${reply.software} is checked with all your software. ` : ''
      return `${software}${crossesOf(reply, view).length > 0 ? 'Here’s the change, but I can’t do every part of it.' : 'Here’s the change. Nothing changes until you save it.'}`
    }
  }
}

/** Where a later version was made, once one exists after `mine`. Null while none does. */
export function changedSince(live: Pick<UseCaseView, 'version'> | undefined, versions: readonly VersionView[] | undefined, mine: number): string | null {
  if (!live || live.version <= mine) return null
  const newest = versions?.find((version) => version.version > mine)
  const where = newest?.via === 'chat' ? ', in a later answer' : newest?.via === 'page' ? ', on its page' : ''
  return `Changed again since${where}.`
}

/** What follows a save, as the workflow is now: paused, or running from its next run. */
export interface Now {
  readonly paused: boolean
  /** "Mon 2 Nov, 8:00", or null when it has no next run. */
  readonly next: string | null
}

const PAUSED = 'is paused, so it won’t run until you resume it.'

type Undone = Parameters<typeof undoneWords>[0]

/** The sentence once she saved, undid or backed out. `since` is set once the workflow changed again after the card's version. */
export function doneSay(phase: Exclude<Phase, { kind: 'open' }>, now: Now, since: string | null, live: Undone | undefined): string {
  switch (phase.kind) {
    case 'kept':
      return 'No problem. Nothing changed.'
    case 'saved': {
      const name = phase.target.name
      if (since !== null && phase.version !== null) return `Saved as version ${String(phase.version)}. ${since}`
      if (phase.target.watchlist) return `Saved.${now.next ? ` Next run ${now.next}.` : ''} You now own this schedule, so you can’t approve its checks.`
      return now.paused ? `Saved. ${name} ${PAUSED}` : `Saved. ${name} runs ${repeatWords(phase.after)} now.`
    }
    case 'undone':
      if (since !== null) return `Undone, as version ${String(phase.version)}. ${since}`
      return live ? undoneWords(live) : `Undone, as version ${String(phase.version)}.`
  }
}

/** The card's last line once saved or undone. Undo shows only while it can keep what it promises. */
export function doneLine(phase: Extract<Phase, { kind: 'saved' | 'undone' }>, now: Now, since: string | null): { readonly words: string; readonly undo: boolean } {
  if (phase.kind === 'undone') return { words: `Undone, as version ${String(phase.version)}.${since ? ` ${since}` : ''}`, undo: false }
  const later = now.paused ? 'It’s paused, so it won’t run until you resume it.' : now.next ? `Next run ${now.next}.` : ''
  if (phase.version === null) return { words: `Saved.${later ? ` ${later}` : ''}`, undo: false }
  if (since !== null) return { words: `Saved as version ${String(phase.version)}. ${since}`, undo: false }
  return { words: `Saved as version ${String(phase.version)}.${later ? ` ${later}` : ''}`, undo: true }
}

/**
 * The version a save published, or null when it published none. The schedule route publishes nothing when the schedule was
 * already so, and answers with the version running, which may be a teammate's. So a version counts as this save's only when it
 * is the newest, hers, from the chat, and newer than the one the card knew of. Undo then never undoes someone else's change.
 */
export function publishedVersion(target: EditChoice, saved: Pick<UseCaseView, 'version'>, newest: VersionView | undefined, me: string | undefined, known: number | undefined): number | null {
  if (target.watchlist || newest === undefined || me === undefined) return null
  if (newest.version !== saved.version || newest.by !== me || newest.via !== 'chat') return null
  return known === undefined || saved.version > known ? saved.version : null
}
