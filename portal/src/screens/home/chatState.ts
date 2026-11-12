import { EMPTY, threadReducer, type Thread, type ThreadAction } from './threadState'

/** What Home keeps for one person between visits: the conversation, the words in the box and the line under it, and a message waiting to be read. */
export interface Desk {
  readonly thread: Thread
  readonly text: string
  readonly problem: string | null
  readonly note: Note | null
}

export interface Note {
  readonly id: number
  readonly text: string
}

export const EMPTY_DESK: Desk = { thread: EMPTY, text: '', problem: null, note: null }

/** One desk for each person, so signing in as someone else never shows the last person's chat (spec 5.3). */
export type Desks = Readonly<Record<string, Desk>>

export type DeskAction =
  | ThreadAction
  | { readonly type: 'typed'; readonly text: string }
  | { readonly type: 'problem'; readonly problem: string | null }
  | { readonly type: 'note'; readonly text: string }
  | { readonly type: 'note_read' }

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
    case 'sent':
      return { ...desk, thread: threadReducer(desk.thread, action), text: '', problem: null }
    case 'new_chat':
      return { ...desk, thread: EMPTY, text: '', problem: null }
    default:
      return { ...desk, thread: threadReducer(desk.thread, action) }
  }
}

/** The action is for one person's desk, named when it was sent, because an answer can arrive after the person has changed. */
export function desksReducer(desks: Desks, { user, action }: { readonly user: string; readonly action: DeskAction }): Desks {
  return { ...desks, [user]: deskReducer(deskOf(desks, user), action) }
}
