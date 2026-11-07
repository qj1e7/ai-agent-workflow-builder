import type { PlannerReply } from '../../api/types'
import type { CardStart } from './SetupCard'

export type Message =
  | { readonly kind: 'me'; readonly id: number; readonly text: string }
  | { readonly kind: 'thinking'; readonly id: number }
  | { readonly kind: 'reply'; readonly id: number; readonly reply: PlannerReply; /** What the person typed, or the chip’s words. */ readonly typed: string }
  | { readonly kind: 'card'; readonly id: number; readonly start: CardStart }

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
    case 'failed':
      return { ...state, messages: state.messages.slice(0, -2) }
    case 'resumed':
      return { messages: [{ kind: 'card', id: state.last + 1, start: action.start }], last: state.last + 1 }
    case 'new_chat':
      return EMPTY
  }
}

export const isThinking = (thread: Thread): boolean => thread.messages.some((m) => m.kind === 'thinking')
