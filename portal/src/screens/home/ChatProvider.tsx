import { createContext, useCallback, useContext, useMemo, useReducer, useRef, type ReactNode } from 'react'
import { useCacheScope } from '../../api/context'
import { usePlannerAnswer } from '../../api/plannerQueries'
import type { PlannerAnswerIn } from '../../api/types'
import { deskOf, desksReducer, type DeskAction, type Desks, type Note } from './chatState'
import type { CardKept, CardMemory } from './cardMemory'
import type { CardStart } from './SetupCard'
import { isThinking, previousOf, type Thread } from './threadState'

export const SEND_FAILED = 'That didn’t send. Try again.'
export const DRAFT_SAVED = 'Your draft is saved. Find it on Workflows.'

export interface Chat {
  readonly thread: Thread
  readonly text: string
  readonly problem: string | null
  readonly note: Note | null
  readonly busy: boolean
  readonly type: (text: string) => void
  readonly setProblem: (problem: string | null) => void
  /** Sends words, or an intent, to the Planner. `restore` is put back in the box when the send fails. */
  readonly send: (ask: PlannerAnswerIn, shown: string, restore: string | null) => void
  /** Sends what is in the box, following on from the last answer. */
  readonly sendText: () => void
  readonly resume: (start: CardStart) => void
  readonly newChat: () => void
  readonly readNote: () => void
  /** Where the conversation was scrolled to when Home was left. It is never saved. */
  readonly scroll: { readonly get: () => number; readonly set: (top: number) => void }
  readonly cardMemory: (messageId: number) => CardMemory
}

const ChatContext = createContext<Chat | null>(null)

interface Kept {
  readonly kept: CardKept
  readonly save: () => void
}

/**
 * The conversation with the Planner, above the routes. Going to Workflows or the Watchlist and back returns it where it was.
 * Each signed-in person has their own. It lives in memory only: the chat is not the record, so a reload starts fresh.
 * `initial` seeds the desks, for a test.
 */
export function ChatProvider({ children, initial = {} }: { children: ReactNode; initial?: Desks }) {
  const user = useCacheScope()
  const { mutateAsync: askPlanner } = usePlannerAnswer()
  const [desks, dispatch] = useReducer(desksReducer, initial)
  const scrolls = useRef(new Map<string, number>())
  const cards = useRef(new Map<string, Kept>())
  const desk = deskOf(desks, user)
  const { thread } = desk
  const busy = isThinking(thread)

  const act = useCallback((owner: string) => (action: DeskAction) => dispatch({ user: owner, action }), [])

  const send = useCallback(
    (ask: PlannerAnswerIn, shown: string, restore: string | null) => {
      const to = act(user)
      to({ type: 'sent', text: shown })
      askPlanner(ask).then(
        (reply) => to({ type: 'answered', reply, typed: shown }),
        () => {
          to({ type: 'failed' })
          if (restore !== null) to({ type: 'typed', text: restore })
          to({ type: 'problem', problem: SEND_FAILED })
        },
      )
    },
    [act, askPlanner, user],
  )

  const value = useMemo<Chat>(() => {
    const here = act(user)
    const memoryKey = (messageId: number) => `${user}:${String(messageId)}`
    const unfinished = () => [...cards.current].filter(([key, card]) => key.startsWith(`${user}:`) && card.kept.phase.kind === 'open')
    return {
      thread,
      text: desk.text,
      problem: desk.problem,
      note: desk.note,
      busy,
      type: (text) => here({ type: 'typed', text }),
      setProblem: (problem) => here({ type: 'problem', problem }),
      send,
      sendText: () => {
        const typed = desk.text.trim()
        if (typed === '' || busy) return
        const previous = previousOf(thread)
        send(previous === null ? { text: typed } : { text: typed, previous }, typed, desk.text)
      },
      resume: (start) => here({ type: 'resumed', start }),
      newChat: () => {
        const open = unfinished()
        for (const [, card] of open) card.save()
        for (const [key] of [...cards.current]) if (key.startsWith(`${user}:`)) cards.current.delete(key)
        scrolls.current.delete(user)
        here({ type: 'new_chat' })
        if (open.length > 0) here({ type: 'note', text: DRAFT_SAVED })
      },
      readNote: () => here({ type: 'note_read' }),
      scroll: { get: () => scrolls.current.get(user) ?? 0, set: (top) => void scrolls.current.set(user, top) },
      cardMemory: (messageId) => ({
        kept: cards.current.get(memoryKey(messageId))?.kept,
        keep: (kept, save) => void cards.current.set(memoryKey(messageId), { kept, save }),
      }),
    }
  }, [act, busy, desk.note, desk.problem, desk.text, send, thread, user])

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): Chat {
  const chat = useContext(ChatContext)
  if (!chat) throw new Error('ChatProvider is missing above this component.')
  return chat
}
