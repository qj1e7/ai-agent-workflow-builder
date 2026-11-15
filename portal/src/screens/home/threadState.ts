import type { PlannerAnswerIn, PlannerReply } from '../../api/types'
import type { CardStart } from './SetupCard'

export type Message =
  | { readonly kind: 'me'; readonly id: number; readonly text: string }
  | { readonly kind: 'thinking'; readonly id: number }
  | { readonly kind: 'reply'; readonly id: number; readonly reply: PlannerReply; /** What the person typed, or the chip’s words. */ readonly typed: string }
  | { readonly kind: 'card'; readonly id: number; readonly start: CardStart }
  /** The watchlist’s newer versions, drawn from the watchlist itself with no model, so it needs no Planner reply. */
  | { readonly kind: 'behind'; readonly id: number }

export interface Thread {
  readonly messages: readonly Message[]
  readonly last: number
}

export const EMPTY: Thread = { messages: [], last: 0 }

export type ThreadAction =
  | { readonly type: 'sent'; readonly text: string }
  | { readonly type: 'answered'; readonly reply: PlannerReply; readonly typed: string }
  | { readonly type: 'failed' }
  /** A version someone published in n8n, found while the chat is open. It comes with no message from the person before it. */
  | { readonly type: 'arrived'; readonly reply: PlannerReply }
  | { readonly type: 'resumed'; readonly start: CardStart }
  | { readonly type: 'asked_behind'; readonly text: string }
  | { readonly type: 'new_chat' }

/** The thread lives only on the page. It is never saved: the chat is not the record. */
export function threadReducer(state: Thread, action: ThreadAction): Thread {
  switch (action.type) {
    case 'sent': {
      const me = state.last + 1
      return { messages: [...state.messages, { kind: 'me', id: me, text: action.text }, { kind: 'thinking', id: me + 1 }], last: me + 1 }
    }
    case 'answered':
      return { ...state, messages: state.messages.map((m) => (m.kind === 'thinking' ? { kind: 'reply', id: m.id, reply: action.reply, typed: action.typed } : m)) }
    case 'asked_behind': {
      const me = state.last + 1
      return { messages: [...state.messages, { kind: 'me', id: me, text: action.text }, { kind: 'behind', id: me + 1 }], last: me + 1 }
    }
    case 'arrived': {
      // A request still waiting for its answer stays last, so a failed send takes back only the request.
      const card: Message = { kind: 'reply', id: state.last + 1, reply: action.reply, typed: '' }
      const waiting = isThinking(state) ? state.messages.slice(-2) : []
      const before = state.messages.slice(0, state.messages.length - waiting.length)
      return { messages: [...before, card, ...waiting], last: state.last + 1 }
    }
    case 'failed':
      return { ...state, messages: state.messages.slice(0, -2) }
    case 'resumed':
      return { messages: [...state.messages, { kind: 'card', id: state.last + 1, start: action.start }], last: state.last + 1 }
    case 'new_chat':
      return EMPTY
  }
}

/** A message the Planner answered, however it was made. */
export const isAnswer = (message: Message): boolean => message.kind === 'reply' || message.kind === 'behind'

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

export function previousOf(thread: Thread): PreviousTurn | null {
  // A Changed in n8n card answers no question, so a request typed after it follows on from the last answer to a person.
  const last = thread.messages.findLast((m) => m.kind === 'reply' && m.reply.answer !== 'changed_in_n8n')
  if (last === undefined || last.kind !== 'reply' || last.reply.answer === 'offline' || last.reply.answer === 'changed_in_n8n') return null
  const { reply, typed } = last
  return {
    request: typed,
    software: reply.answer === 'watchlist' ? reply.software : null,
    answer: reply.answer === 'question' || reply.answer === 'reply' ? reply.text : null,
    // The runtime refuses a second clarifying question in a row, and tells one from an answer by this word.
    kind: reply.answer === 'reply' && reply.form === 'clarify' ? 'reply_clarify' : reply.answer,
  }
}
