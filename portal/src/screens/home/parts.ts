import type { CantReply, PartReason, PartView, PlannerReply, ScheduleView } from '../../api/types'
import { clockWords, repeatWords } from '../software/software'
import { andList, clashChosen, isClash, type When } from './card'

/** The four marks of spec 6.5: a tick, a cross, the one question asked now, and a question that waits its turn. */
export type Mark = 'ok' | 'no' | 'ask' | 'later'

export const MARK_WORDS: Readonly<Record<Mark, string>> = { ok: 'Will do', no: 'Can’t do', ask: 'Question', later: 'Question for later' }

/** The mark of one of the set-up card's parts, Watch, When or Then, from what it holds: the question asked now, else a part it can't do, else a question for later, else a tick. */
export function partMark(marks: readonly Mark[]): Mark {
  for (const mark of ['ask', 'no', 'later'] as const) if (marks.includes(mark)) return mark
  return 'ok'
}

export const ASKED_NEXT = 'Asked next'

export const quote = (text: string): string => `“${text}”`

const REASON_WORDS: Readonly<Record<PartReason, string>> = {
  not_followed: 'I didn’t follow this part.',
  cant_do: 'I can’t do this part yet.',
  ask_on_its_own: 'Ask this on its own, and I’ll answer it.',
  one_day: 'I can only set one day.',
  one_time: 'I can only set one time.',
  one_frequency: 'I can only set one schedule.',
  own_time: 'The Software watchlist checks all your software together, on one schedule. I can’t give one software its own time yet.',
  skip_approval: 'Anything that changes data waits for a yes, every time.',
  with_a_yes: 'This waits until it’s set up with a yes.',
  needs_the_rest: 'It can’t run without the part I can’t do.',
  how_many_days: 'Your words don’t say how many days.',
  operators: 'Operators set up workflows.',
  only_schedule: 'From the chat I can only change when it runs.',
  how_often: 'I can’t run things that often yet.',
}

/**
 * What the words of a cross are read against: the card’s schedule, the Software watchlist’s schedule for a watch request, who
 * makes changes, named from the People list, for a change asked by someone who isn’t an Operator, and the workflow an edit changes.
 */
export interface CrossContext {
  readonly when?: When
  readonly watchlist?: ScheduleView | null
  readonly operators?: string
  readonly workflow?: string
  /** The edit changes the Software watchlist, so a change it can't make names what the chat can do to the watchlist. */
  readonly editsWatchlist?: boolean
  /** The set-up card names each cross in the sketch's short form, her words as a sentence, rather than quoted. */
  readonly short?: boolean
}

export const WATCHLIST_CANT = 'From the chat I can add software to the Software watchlist, remove it, or change when the watchlist runs.'

/** The request that moves the whole Software watchlist to the time she asked of one software. */
export const watchlistRuns = (time: string): string => `Make the Software watchlist run ${time.trim()}`

/** “every weekday except Friday” or “skip Fridays” leaves a day out, which no schedule here can hold. Anything else reads as how often. */
const LEAVES_OUT = /\b(?:except|excluding|but not|apart from|other than|skip|skipping|never|not on|no longer|don[’']t|do not|stop|stopping|without)\b/i
const STARTS_WITH_A_DAY = /^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b/i

export function howOftenWords(text: string): string {
  const said = text.trim()
  if (said === '') return REASON_WORDS.how_often
  if (LEAVES_OUT.test(said)) return 'I can’t leave days out of a schedule yet.'
  // The whole phrase is their words, as a sentence: “Every other Friday” reads “every other Friday”, and a day stays a name.
  const inSentence = STARTS_WITH_A_DAY.test(said) ? said : `${said.charAt(0).toLowerCase()}${said.slice(1)}`
  return `I can’t run things ${inSentence} yet.`
}

/** Why a part has a cross or a question, in the prototype’s words. A can’t names the registry’s reason. */
export function crossWords(part: PartView, context: CrossContext = {}): string {
  if (part.reason === null) return part.mark === 'question' ? REASON_WORDS.how_many_days : REASON_WORDS.not_followed
  if (part.reason === 'cant_do' && part.note !== null && part.note.trim() !== '') return part.note
  if (part.reason === 'operators' && context.operators) return context.operators
  if (part.reason === 'how_often') return howOftenWords(part.text)
  if (part.reason === 'only_schedule' && context.editsWatchlist === true) return WATCHLIST_CANT
  if (part.reason === 'only_schedule' && context.workflow) return `From the chat I can only change when ${context.workflow} runs.`
  if (part.reason === 'own_time' && context.watchlist)
    return `The Software watchlist checks all your software together, ${repeatWords(context.watchlist)}. I can’t give one software its own time yet.`
  const chosen = context.when && isClash(part) ? clashChosen(context.when, part) : null
  if (chosen !== null && context.when) {
    if (part.reason === 'one_day') return `I can only set one day, so it runs on ${chosen} only.`
    if (part.reason === 'one_time') return `I can only set one time, so it runs at ${clockWords(context.when.at)} only.`
  }
  return REASON_WORDS[part.reason]
}

const asSentence = (text: string): string => {
  const said = text.trim().replace(/[.!?]+$/, '')
  return `${said.charAt(0).toUpperCase()}${said.slice(1)}.`
}

/** Her words for a cross, quoted, or as a sentence in the short form. Once she picks one of a clash’s choices, only the others are named. */
export function crossLabel(part: PartView, when?: When, short = false): string {
  const chosen = when && isClash(part) ? clashChosen(when, part) : null
  const others = chosen === null ? [] : part.choices.filter((choice) => choice !== chosen)
  // A clause it didn't follow stays in her own words, quoted, as the sketch keeps it.
  if (short && part.reason !== 'not_followed' && part.reason !== null) return asSentence(others.length > 0 ? andList(others) : part.text)
  return others.length > 0 ? andList(others.map(quote)) : quote(part.text)
}

/**
 * What a cross sends as its own message when she taps Ask about this (ADR 0047): a clause the Planner didn’t follow, or a
 * question it answers on its own. A time on a watch request has the Software watchlist’s offer instead, and the rest already sit
 * on a card with its own button. Null when the cross has no such step.
 */
export function askOfCross(part: PartView): string | null {
  const reason: PartReason | null = part.reason ?? (part.mark === 'cant' ? 'not_followed' : null)
  switch (reason) {
    case 'not_followed':
    case 'ask_on_its_own':
      return part.text.trim() === '' ? null : part.text
    case 'own_time':
    case null:
    case 'cant_do':
    case 'one_day':
    case 'one_time':
    case 'one_frequency':
    case 'skip_approval':
    case 'with_a_yes':
    case 'needs_the_rest':
    case 'how_many_days':
    case 'operators':
    case 'only_schedule':
    case 'how_often':
      return null
  }
}

/** Every cross and question of a request, for the card that sets up the part the Planner can do. A watch request’s own time isn’t the card’s. */
export const crossesOnCard = (part: PartView): boolean => part.mark !== 'will_do' && part.reason !== 'needs_the_rest' && part.reason !== 'own_time'

/** What a can’t answer’s alternative set-up card keeps: every cross and question but the can’t, which its own card names. */
export const crossesInstead = (part: PartView): boolean => crossesOnCard(part) && part.reason !== 'cant_do'

/**
 * Whether a can’t answer is really the part the Planner can do (spec 6.3): a set-up card with a cross on each part it can’t do.
 * That holds when every part it can’t do is a clause it didn’t follow, or a filter or tool the team could add to a system the
 * platform already reaches. A system it doesn’t reach, such as email, stays a can’t with an alternative.
 */
export const cantOnCard = (reply: CantReply): boolean => reply.alternative?.answer === 'setup_card' && reply.cant.every((row) => row.needs !== 'new_system')

/** What a set-up card inside another answer asks itself, since it runs on that schedule and search: a clash and how many days. */
export const asksOnCard = (part: PartView): boolean => isClash(part) || part.reason === 'how_many_days'

/** Whether the Planner followed none of what was typed, so its card says so instead of listing what it can do. */
export const followedNothing = (reply: PlannerReply): boolean => reply.parts.length > 0 && reply.parts.every((part) => part.reason === 'not_followed')

/** Whether a set-up card is drawn somewhere inside the answer. */
function holdsCard(reply: PlannerReply): boolean {
  if (reply.answer === 'setup_card' || reply.answer === 'part') return true
  if (reply.answer === 'cant') return reply.alternative !== null && holdsCard(reply.alternative)
  return reply.answer === 'watchlist' && reply.also !== null && holdsCard(reply.also)
}

/**
 * The clauses an answer didn’t read, which it draws above its card (spec 6.5). A free reply answers the whole message, and the
 * fallback card replaces the crosses, so neither draws any. The set-up card and the edit card mark their own parts. The can’t
 * answer’s card already names what it can’t do, so only the clauses it didn’t read are added. A card inside the answer asks its
 * own clash and days, so they aren’t drawn twice. A refusal that offers a set-up with a yes draws none, and one that offers none
 * draws why it can’t do the rest, past the skip its card names. Which software, places to start and the offline answer draw none.
 */
export function leftoverParts(reply: PlannerReply): PartView[] {
  const above = (parts: readonly PartView[]) => parts.filter((part) => part.mark !== 'will_do' && !(holdsCard(reply) && asksOnCard(part)))
  switch (reply.answer) {
    case 'setup_card':
    case 'part':
    case 'edit':
    case 'changed_in_n8n':
    case 'which_software':
    case 'ideas':
    case 'offline':
    case 'reply':
    case 'didnt_follow':
    case 'draft_started':
      return []
    case 'cant': {
      // The card names only the can'ts with something to build. One with nothing to build, as a yes that can't be skipped, is drawn here.
      const named = (part: PartView) => reply.cant.some((row) => row.needs !== null && row.text.trim().toLowerCase() === part.text.trim().toLowerCase())
      return reply.alternative?.answer === 'setup_card' ? [] : above(reply.parts.filter((part) => !(part.reason === 'cant_do' && named(part)) && part.reason !== 'needs_the_rest'))
    }
    case 'refused':
      return reply.rest.trim() === '' ? above(reply.parts.filter((part) => part.reason !== 'skip_approval')) : []
    case 'operators':
      // The answer’s sentence already says who makes the changes, so only a question beside them is marked.
      return above(reply.parts.filter((part) => part.reason !== 'operators'))
    case 'abilities':
      // A request it followed none of gets one card that says so, in place of the crosses.
      return followedNothing(reply) ? [] : above(reply.parts)
    case 'pause':
    case 'resume':
    case 'remove_software':
    case 'explain':
    case 'watchlist':
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
    case 'question':
    case 'decided':
    case 'decide':
    case 'n8n':
      return above(reply.parts)
  }
}
