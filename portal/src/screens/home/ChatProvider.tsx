import { createContext, useCallback, useContext, useMemo, useReducer, useRef, type ReactNode } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useChangeDrafted } from '../../api/draftedQueries'
import { usePlannerAnswer } from '../../api/plannerQueries'
import type { ChangedInN8nReply, PlannerAnswerIn } from '../../api/types'
import type { PanelItem } from '../../ui/sidePanel'
import { deskOf, desksReducer, panelOf, type Changing, type DeskAction, type Desks, type Note } from './chatState'
import { newCardMemory, type CardMemory } from './cardMemory'
import { arrivalKey, unseenArrivals } from './changed'
import type { CardStart } from './SetupCard'
import { askOf, chatOf, isThinking, type Thread } from './threadState'

export const SEND_FAILED = 'That didn’t send. Try again.'
export const DRAFT_SAVED = 'Your draft is saved. Find it on Workflows.'

export interface OpenPanel {
  readonly item: PanelItem
  /** Which of the chat's ways to open the item was pressed, counted in page order, so Close hands focus back to it. Null when an answer showed it. */
  readonly from: number | null
  /** The item Back returns to, when the panel was opened from inside another, such as an item from its list. */
  readonly previous: PanelItem | null
  /** The first item, which the chat's control opened, so Close hands focus back to that control. */
  readonly root: PanelItem
}

export interface Chat {
  readonly thread: Thread
  readonly text: string
  readonly problem: string | null
  readonly note: Note | null
  /** The drafted workflow the next message changes, or null. */
  readonly changing: Changing | null
  readonly startChange: (changing: Changing) => void
  readonly cancelChange: () => void
  readonly busy: boolean
  readonly type: (text: string) => void
  readonly setProblem: (problem: string | null) => void
  /** Sends words, or an intent, to the Planner. `restore` is put back in the box when the send fails. */
  readonly send: (ask: PlannerAnswerIn, shown: string, restore: string | null) => void
  /** Asks which software is behind. The watchlist answers it, with no model, so nothing goes to the Planner. */
  readonly askBehind: (shown: string) => void
  /** Sends what is in the box, following on from the last answer. */
  readonly sendText: () => void
  /** Sends words they tapped, such as a choice or an offer, following on from the last answer as typed words do. */
  readonly sendWords: (words: string) => void
  readonly resume: (start: CardStart) => void
  /** Shows each version published in n8n that this chat has not shown yet, oldest first. A new chat does not show one again. */
  readonly arrive: (found: readonly ChangedInN8nReply[]) => void
  /** Shows the card of a drafted workflow they started with a button. */
  readonly arriveDraft: (draftedId: string) => void
  /** Puts a new card for a drafted workflow's revision in the thread, so the older card settles. */
  readonly arriveRevision: (draftedId: string, revision: number) => void
  readonly newChat: () => void
  readonly readNote: () => void
  /** Shows words in Home's one message at the bottom of the page, as the side panel does after a decline. */
  readonly say: (text: string) => void
  /** Where the conversation was scrolled to when Home was left. It is never saved. */
  readonly scroll: { readonly get: () => number; readonly set: (top: number) => void }
  readonly cardMemory: (messageId: number) => CardMemory
  /** What the side panel shows beside the chat. It is kept across pages, so a page opened from the panel comes back to it. */
  readonly panel: OpenPanel | null
  readonly openPanel: (item: PanelItem, from: number | null) => void
  /** Opens an item from inside the panel, keeping the panel's current item behind it for Back. */
  readonly pushPanel: (item: PanelItem) => void
  readonly backPanel: () => void
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
  const { mutateAsync: changeDrafted } = useChangeDrafted()
  const words = useErrorWords()
  const changeBusy = useRef(false)
  const [desks, dispatch] = useReducer(desksReducer, initial)
  const scrolls = useRef(new Map<string, number>())
  const cards = useRef(new Map<string, CardMemory>())
  const arrived = useRef(new Map<string, Set<string>>())
  const desk = deskOf(desks, user)
  const panel = useMemo(() => panelOf(desk.panel), [desk.panel])
  const { thread } = desk
  const busy = isThinking(thread)

  const act = useCallback((owner: string) => (action: DeskAction) => dispatch({ user: owner, action }), [])
  const openPanel = useCallback((item: PanelItem, from: number | null) => act(user)({ type: 'panel_open', item, from }), [act, user])
  const pushPanel = useCallback((item: PanelItem) => act(user)({ type: 'panel_push', item }), [act, user])
  const backPanel = useCallback(() => act(user)({ type: 'panel_back' }), [act, user])
  const closePanel = useCallback(() => act(user)({ type: 'panel_close' }), [act, user])

  const send = useCallback(
    (ask: PlannerAnswerIn, shown: string, restore: string | null) => {
      const to = act(user)
      const chat = chatOf(thread)
      to({ type: 'sent', text: shown, chat })
      askPlanner({ ...ask, chat }).then(
        (reply) => to({ type: 'answered', reply, typed: shown }),
        () => {
          to({ type: 'failed' })
          if (restore !== null) to({ type: 'typed', text: restore })
          to({ type: 'problem', problem: SEND_FAILED })
        },
      )
    },
    [act, askPlanner, thread, user],
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
      changing: desk.changing,
      startChange: (changing) => here({ type: 'change_start', changing }),
      cancelChange: () => here({ type: 'change_cancel' }),
      busy,
      type: (text) => here({ type: 'typed', text }),
      setProblem: (problem) => here({ type: 'problem', problem }),
      send,
      askBehind: (shown) => here({ type: 'asked_behind', text: shown }),
      sendText: () => {
        const typed = desk.text.trim()
        if (typed === '' || busy) return
        const changing = desk.changing
        if (changing !== null) {
          if (changeBusy.current) return
          changeBusy.current = true
          changeDrafted({ draftedId: changing.draftedId, words: typed, revision: changing.revision }).then(
            (view) => here({ type: 'changed', text: typed, draftedId: changing.draftedId, revision: view.card_revision }),
            (error: unknown) => here({ type: 'problem', problem: words(error) }),
          ).finally(() => {
            changeBusy.current = false
          })
          return
        }
        send(askOf(typed, thread), typed, desk.text)
      },
      sendWords: (words) => {
        if (!busy) send(askOf(words, thread), words, null)
      },
      resume: (start) => here({ type: 'resumed', start }),
      arrive: (found) => {
        const seen = arrived.current.get(user) ?? new Set<string>()
        arrived.current.set(user, seen)
        for (const reply of unseenArrivals(found, seen)) {
          seen.add(arrivalKey(reply))
          here({ type: 'arrived', reply })
        }
      },
      arriveDraft: (draftedId) => here({ type: 'arrived', reply: { answer: 'draft_started', drafted_id: draftedId, refused: null, parts: [], trace_id: null } }),
      arriveRevision: (draftedId, revision) => here({ type: 'draft_card', draftedId, revision }),
      // A card they hadn't finished saves itself as a draft as it leaves the page, so New chat only needs to know there was one.
      newChat: () => {
        const unfinished = thread.messages.some((message) => cards.current.get(`${user}:${String(message.id)}`)?.kept()?.phase.kind === 'open')
        for (const key of [...cards.current.keys()]) if (key.startsWith(`${user}:`)) cards.current.delete(key)
        scrolls.current.delete(user)
        here({ type: 'new_chat' })
        if (unfinished) here({ type: 'note', text: DRAFT_SAVED })
      },
      readNote: () => here({ type: 'note_read' }),
      say: (text) => here({ type: 'note', text }),
      scroll,
      cardMemory,
      panel,
      openPanel,
      pushPanel,
      backPanel,
      closePanel,
    }
  }, [act, backPanel, busy, cardMemory, changeDrafted, closePanel, desk.changing, desk.note, desk.problem, desk.text, openPanel, panel, pushPanel, scroll, send, thread, user, words])

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

/** Home's one message at the bottom of the page, for a card's short note. Outside the chat, as in a test of one card, it says nothing. */
export function useNote(): (text: string) => void {
  return useContext(ChatContext)?.say ?? NO_NOTE
}

const NO_NOTE = (): void => undefined

export function useChat(): Chat {
  const chat = useContext(ChatContext)
  if (!chat) throw new Error('ChatProvider is missing above this component.')
  return chat
}

/** Starts a change to a drafted workflow, or null outside the chat, where there is no box to put it in. */
export function useAskForChange(): ((changing: Changing) => void) | null {
  const chat = useContext(ChatContext)
  return chat === null ? null : chat.startChange
}

/** Adds a drafted workflow's card to the thread, as an answer with no message of theirs before it. Null outside the chat. */
export function useShowDraft(): ((draftedId: string) => void) | null {
  const chat = useContext(ChatContext)
  return chat === null ? null : chat.arriveDraft
}

/** Puts a new card for a drafted workflow's revision in the thread, or null outside the chat. */
export function useShowRevision(): ((draftedId: string, revision: number) => void) | null {
  const chat = useContext(ChatContext)
  return chat === null ? null : chat.arriveRevision
}
