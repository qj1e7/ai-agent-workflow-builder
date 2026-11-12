import { createContext, useCallback, useContext, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import { useCacheScope } from '../../api/context'
import { usePlannerAnswer } from '../../api/plannerQueries'
import type { PlannerAnswerIn } from '../../api/types'
import type { PanelItem } from '../../ui/sidePanel'
import { deskOf, desksReducer, type DeskAction, type Desks, type Note } from './chatState'
import { newCardMemory, type CardMemory } from './cardMemory'
import type { CardStart } from './SetupCard'
import { isThinking, previousOf, type Thread } from './threadState'

export const SEND_FAILED = 'That didn’t send. Try again.'
export const DRAFT_SAVED = 'Your draft is saved. Find it on Workflows.'

export interface OpenPanel {
  readonly item: PanelItem
  /** Which of the chat's ways to open the item was pressed, counted in page order, so Close hands focus back to it. */
  readonly from: number
}

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
  /** Shows words in Home's one message at the bottom of the page, as the side panel does after a decline. */
  readonly say: (text: string) => void
  /** Where the conversation was scrolled to when Home was left. It is never saved. */
  readonly scroll: { readonly get: () => number; readonly set: (top: number) => void }
  readonly cardMemory: (messageId: number) => CardMemory
  /** What the side panel shows beside the chat. It is kept across pages, so a page opened from the panel comes back to it. */
  readonly panel: OpenPanel | null
  readonly openPanel: (item: PanelItem, from: number) => void
  readonly closePanel: () => void
}

const ChatContext = createContext<Chat | null>(null)

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
  const cards = useRef(new Map<string, CardMemory>())
  const [shown, setShown] = useState<{ readonly user: string; readonly panel: OpenPanel } | null>(null)
  const panel = shown?.user === user ? shown.panel : null
  const openPanel = useCallback((item: PanelItem, from: number) => setShown({ user, panel: { item, from } }), [user])
  const closePanel = useCallback(() => setShown(null), [])
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

  const scroll = useMemo(() => ({ get: () => scrolls.current.get(user) ?? 0, set: (top: number) => void scrolls.current.set(user, top) }), [user])

  const cardMemory = useCallback(
    (messageId: number): CardMemory => {
      const key = `${user}:${String(messageId)}`
      const known = cards.current.get(key)
      if (known) return known
      const memory = newCardMemory()
      cards.current.set(key, memory)
      return memory
    },
    [user],
  )

  const value = useMemo<Chat>(() => {
    const here = act(user)
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
      // A card she hadn't finished saves itself as a draft as it leaves the page, so New chat only needs to know there was one.
      newChat: () => {
        const unfinished = thread.messages.some((message) => cards.current.get(`${user}:${String(message.id)}`)?.kept()?.phase.kind === 'open')
        for (const key of [...cards.current.keys()]) if (key.startsWith(`${user}:`)) cards.current.delete(key)
        scrolls.current.delete(user)
        setShown(null)
        here({ type: 'new_chat' })
        if (unfinished) here({ type: 'note', text: DRAFT_SAVED })
      },
      readNote: () => here({ type: 'note_read' }),
      say: (text) => here({ type: 'note', text }),
      scroll,
      cardMemory,
      panel,
      openPanel,
      closePanel,
    }
  }, [act, busy, cardMemory, closePanel, desk.note, desk.problem, desk.text, openPanel, panel, scroll, send, thread, user])

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): Chat {
  const chat = useContext(ChatContext)
  if (!chat) throw new Error('ChatProvider is missing above this component.')
  return chat
}
