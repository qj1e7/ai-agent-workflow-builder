import type { PanelItem } from '../../ui/sidePanel'
import { panelKey } from '../../ui/sidePanel'
import { EMPTY, threadReducer, type Thread, type ThreadAction } from './threadState'

/** What Home keeps for one person between visits: the conversation, the words in the box and the line under it, and a message waiting to be read. */
export interface Desk {
  readonly thread: Thread
  readonly text: string
  readonly problem: string | null
  readonly note: Note | null
  readonly panel: PanelState | null
}

/** The items the side panel has shown since the chat opened it, the first at the bottom. `from` is the chat control that opened the first, or null when an answer showed it. */
export interface PanelState {
  readonly stack: readonly PanelItem[]
  readonly from: number | null
}

/** The side panel keeps only a short history, enough for Back from an item to its list. */
export const HISTORY_MAX = 6

export interface Note {
  readonly id: number
  readonly text: string
}

export const EMPTY_DESK: Desk = { thread: EMPTY, text: '', problem: null, note: null, panel: null }

/** One desk for each person, so signing in as someone else never shows the last person's chat (spec 5.3). */
export type Desks = Readonly<Record<string, Desk>>

export type DeskAction =
  | ThreadAction
  | { readonly type: 'typed'; readonly text: string }
  | { readonly type: 'problem'; readonly problem: string | null }
  | { readonly type: 'note'; readonly text: string }
  | { readonly type: 'note_read' }
  | { readonly type: 'panel_open'; readonly item: PanelItem; readonly from: number | null }
  | { readonly type: 'panel_push'; readonly item: PanelItem }
  | { readonly type: 'panel_back' }
  | { readonly type: 'panel_close' }

/** What the side panel shows, and the item Back returns to, or null when it is closed. */
export function panelOf(panel: PanelState | null): { readonly item: PanelItem; readonly from: number | null; readonly previous: PanelItem | null; readonly root: PanelItem } | null {
  const item = panel?.stack.at(-1)
  if (!panel || !item) return null
  return { item, from: panel.from, previous: panel.stack.at(-2) ?? null, root: panel.stack[0] ?? item }
}

function pushed(panel: PanelState | null, item: PanelItem): PanelState {
  if (!panel) return { stack: [item], from: null }
  const key = panelKey(item)
  const held = panel.stack.findIndex((held) => panelKey(held) === key)
  const stack = held >= 0 ? panel.stack.slice(0, held + 1) : [...panel.stack, item].slice(-HISTORY_MAX)
  return { ...panel, stack }
}

export const deskOf = (desks: Desks, user: string): Desk => desks[user] ?? EMPTY_DESK

function deskReducer(desk: Desk, action: DeskAction): Desk {
  switch (action.type) {
    case 'typed':
      return { ...desk, text: action.text }
    case 'problem':
      return { ...desk, problem: action.problem }
    case 'note':
      return { ...desk, note: { id: (desk.note?.id ?? 0) + 1, text: action.text } }
    case 'note_read':
      return { ...desk, note: null }
    case 'panel_open':
      return { ...desk, panel: { stack: [action.item], from: action.from } }
    case 'panel_push':
      return { ...desk, panel: pushed(desk.panel, action.item) }
    case 'panel_back':
      return desk.panel && desk.panel.stack.length > 1 ? { ...desk, panel: { ...desk.panel, stack: desk.panel.stack.slice(0, -1) } } : desk
    case 'panel_close':
      return { ...desk, panel: null }
    case 'sent':
      return { ...desk, thread: threadReducer(desk.thread, action), text: '', problem: null }
    case 'new_chat':
      return { ...desk, thread: EMPTY, text: '', problem: null, panel: null }
    default:
      return { ...desk, thread: threadReducer(desk.thread, action) }
  }
}

/** The action is for one person's desk, named when it was sent, because an answer can arrive after the person has changed. */
export function desksReducer(desks: Desks, { user, action }: { readonly user: string; readonly action: DeskAction }): Desks {
  return { ...desks, [user]: deskReducer(deskOf(desks, user), action) }
}
