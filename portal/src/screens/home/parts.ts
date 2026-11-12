import type { PartReason, PartView, PlannerReply, ScheduleView } from '../../api/types'
import { clockWords, repeatWords } from '../software/software'
import { andList, clashChosen, isClash, type When } from './card'

/** The four marks of spec 6.5: a tick, a cross, the one question asked now, and a question that waits its turn. */
export type Mark = 'ok' | 'no' | 'ask' | 'later'

export const MARK_WORDS: Readonly<Record<Mark, string>> = { ok: 'Will do', no: 'Can’t do', ask: 'Question', later: 'Question for later' }

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
}

/** What the words of a cross are read against: the card’s schedule, and the Software watchlist’s schedule for a watch request. */
export interface CrossContext {
  readonly when?: When
  readonly watchlist?: ScheduleView | null
}

/** Why a part has a cross or a question, in the prototype’s words. A can’t names the registry’s reason. */
export function crossWords(part: PartView, context: CrossContext = {}): string {
  if (part.reason === null) return part.mark === 'question' ? REASON_WORDS.how_many_days : REASON_WORDS.not_followed
  if (part.reason === 'cant_do' && part.note !== null && part.note.trim() !== '') return part.note
  if (part.reason === 'own_time' && context.watchlist)
    return `The Software watchlist checks all your software together, ${repeatWords(context.watchlist)}. I can’t give one software its own time yet.`
  const chosen = context.when && isClash(part) ? clashChosen(context.when, part) : null
  if (chosen !== null && context.when) {
    if (part.reason === 'one_day') return `I can only set one day, so it runs on ${chosen} only.`
    if (part.reason === 'one_time') return `I can only set one time, so it runs at ${clockWords(context.when.at)} only.`
  }
  return REASON_WORDS[part.reason]
}

/** Her words for a cross, quoted. Once she picks one of a clash’s choices, only the others are named. */
export function crossLabel(part: PartView, when?: When): string {
  const chosen = when && isClash(part) ? clashChosen(when, part) : null
  const others = chosen === null ? [] : part.choices.filter((choice) => choice !== chosen)
  return others.length > 0 ? andList(others.map(quote)) : quote(part.text)
}

/**
 * The clauses an answer didn’t read, which it draws above its card (spec 6.5). The set-up card marks its own parts. The can’t
 * answer’s card already names what it can’t do, so only the clauses it didn’t read are added. The refusal, which software,
 * places to start and the offline answer draw none.
 */
export function leftoverParts(reply: PlannerReply): PartView[] {
  switch (reply.answer) {
    case 'setup_card':
    case 'part':
    case 'refused':
    case 'which_software':
    case 'ideas':
    case 'offline':
      return []
    case 'cant':
      return reply.parts.filter((part) => part.mark === 'cant' && part.reason !== 'cant_do' && part.reason !== 'needs_the_rest')
    case 'watchlist':
    case 'abilities':
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
    case 'question':
      return reply.parts.filter((part) => part.mark !== 'will_do')
  }
}
