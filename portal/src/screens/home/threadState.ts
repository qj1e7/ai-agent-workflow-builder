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

export function previousOf(thread: Thread): PreviousTurn | null {
  const last = thread.messages.findLast((m) => m.kind === 'reply')
  if (last === undefined || last.kind !== 'reply' || last.reply.answer === 'offline') return null
  const { reply, typed } = last
  return {
    request: typed,
    software: reply.answer === 'watchlist' ? reply.software : null,
    answer: reply.answer === 'question' ? reply.text : null,
    kind: reply.answer,
  }
}
