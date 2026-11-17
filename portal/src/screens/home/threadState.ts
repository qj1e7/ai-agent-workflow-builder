import { newIdempotencyKey } from '../../api/idempotency'
import type { PlannerAnswerIn, PlannerReply } from '../../api/types'
import type { CardStart } from './SetupCard'

export type Message =
  | { readonly kind: 'me'; readonly id: number; readonly text: string }
  | { readonly kind: 'thinking'; readonly id: number }
  | { readonly kind: 'reply'; readonly id: number; readonly reply: PlannerReply; /** What the person typed, or the chip’s words. */ readonly typed: string }
  | { readonly kind: 'card'; readonly id: number; readonly start: CardStart }
  /** The watchlist’s newer versions, drawn from the watchlist itself with no model, so it needs no Planner reply. */
  | { readonly kind: 'behind'; readonly id: number }
  /** A new revision of a drafted workflow, made by a change she asked for in the box. Its card is drawn from the drafted workflow itself. */
  | { readonly kind: 'drafted'; readonly id: number; readonly draftedId: string; readonly revision: number }

export interface Thread {
  readonly messages: readonly Message[]
  readonly last: number
  /** The chat's id, made with its first message, which groups its turns in the Planner's traces (ADR 0050). */
  readonly chat: string | null
}

export const EMPTY: Thread = { messages: [], last: 0, chat: null }

export type ThreadAction =
  | { readonly type: 'sent'; readonly text: string; readonly chat: string }
  | { readonly type: 'answered'; readonly reply: PlannerReply; readonly typed: string }
  | { readonly type: 'failed' }
  /** A version someone published in n8n, found while the chat is open. It comes with no message from the person before it. */
  | { readonly type: 'arrived'; readonly reply: PlannerReply }
  | { readonly type: 'resumed'; readonly start: CardStart }
  | { readonly type: 'asked_behind'; readonly text: string }
  /** A change she asked for was taken: her words, then the new revision's card. */
  | { readonly type: 'changed'; readonly text: string; readonly draftedId: string; readonly revision: number }
  | { readonly type: 'new_chat' }

/** The thread lives only on the page. It is never saved: the chat is not the record. */
export function threadReducer(state: Thread, action: ThreadAction): Thread {
  switch (action.type) {
    case 'sent': {
      const me = state.last + 1
      return { messages: [...state.messages, { kind: 'me', id: me, text: action.text }, { kind: 'thinking', id: me + 1 }], last: me + 1, chat: state.chat ?? action.chat }
    }
    case 'answered':
      return { ...state, messages: state.messages.map((m) => (m.kind === 'thinking' ? { kind: 'reply', id: m.id, reply: action.reply, typed: action.typed } : m)) }
    case 'asked_behind': {
      const me = state.last + 1
      return { ...state, messages: [...state.messages, { kind: 'me', id: me, text: action.text }, { kind: 'behind', id: me + 1 }], last: me + 1 }
    }
    case 'changed': {
      const me = state.last + 1
      return { ...state, messages: [...state.messages, { kind: 'me', id: me, text: action.text }, { kind: 'drafted', id: me + 1, draftedId: action.draftedId, revision: action.revision }], last: me + 1 }
    }
    case 'arrived': {
      // A request still waiting for its answer stays last, so a failed send takes back only the request.
      const card: Message = { kind: 'reply', id: state.last + 1, reply: action.reply, typed: '' }
      const waiting = isThinking(state) ? state.messages.slice(-2) : []
      const before = state.messages.slice(0, state.messages.length - waiting.length)
      return { ...state, messages: [...before, card, ...waiting], last: state.last + 1 }
    }
    case 'failed':
      return { ...state, messages: state.messages.slice(0, -2) }
    case 'resumed':
      return { ...state, messages: [...state.messages, { kind: 'card', id: state.last + 1, start: action.start }], last: state.last + 1 }
    case 'new_chat':
      return EMPTY
  }
}

/** A message the Planner answered, however it was made. */
export const isAnswer = (message: Message): boolean => message.kind === 'reply' || message.kind === 'behind' || message.kind === 'drafted'

export const isThinking = (thread: Thread): boolean => thread.messages.some((m) => m.kind === 'thinking')

/** The turn the next typed request may follow on from: what the person asked, the software the Planner named, and the words it answered with. */
export type PreviousTurn = NonNullable<PlannerAnswerIn['previous']>

/**
 * What goes to the Planner for words she typed or tapped: the words, with the turn before when there is one. A tapped choice
 * carries it too, so the Planner knows it follows a clarifying question and never asks a second one in a row.
 */
export function askOf(text: string, thread: Thread): PlannerAnswerIn {
  const previous = previousOf(thread)
  return previous === null ? { text } : { text, previous }
}

/** The chat a message to the Planner goes in: the thread's own, or a new one for its first message. */
export const chatOf = (thread: Thread, fresh: () => string = newIdempotencyKey): string => thread.chat ?? fresh()

/**
 * The one software an answer named, so a request that only asks to watch it, such as “keep track of it”, means that software. A
 * free reply is left out: its names can be workflows too.
 */
export function softwareNamed(reply: PlannerReply): string | null {
  switch (reply.answer) {
    case 'watchlist':
      return reply.software
    case 'cant':
      return reply.alternative?.answer === 'watchlist' ? reply.alternative.software : null
    case 'question': {
      const [only, ...others] = reply.about_software ?? []
      return others.length === 0 ? (only ?? null) : null
    }
    case 'remove_software': {
      const [only, ...others] = reply.matches
      if (others.length > 0) return null
      return only === undefined ? reply.software : only.name
    }
    default:
      return null
  }
}

export function previousOf(thread: Thread): PreviousTurn | null {
  // A Changed in n8n card answers no question, so a request typed after it follows on from the last answer to a person.
  const last = thread.messages.findLast((m) => m.kind === 'reply' && m.reply.answer !== 'changed_in_n8n')
  if (last === undefined || last.kind !== 'reply' || last.reply.answer === 'offline' || last.reply.answer === 'changed_in_n8n') return null
  const { reply, typed } = last
  // A card since that answer puts something else between them, so “it” no longer points at the software it named.
  const cardSince = thread.messages.slice(thread.messages.indexOf(last) + 1).some((m) => m.kind === 'reply' && m.reply.answer === 'changed_in_n8n')
  return {
    request: typed,
    software: cardSince ? null : softwareNamed(reply),
    answer: reply.answer === 'question' || reply.answer === 'reply' ? reply.text : null,
    // The runtime refuses a second clarifying question in a row, and tells one from an answer by this word.
    kind: reply.answer === 'reply' && reply.form === 'clarify' ? 'reply_clarify' : reply.answer,
    trace_id: reply.trace_id,
  }
}
