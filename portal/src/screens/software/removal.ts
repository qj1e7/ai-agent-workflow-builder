import { ApiError } from '../../api/client'
import type { Latch } from '../../api/latch'

export interface Named {
  readonly id: string
  readonly name: string
}

export type Notice =
  | { readonly kind: 'added'; readonly name: string }
  | { readonly kind: 'removed'; readonly row: Named }
  | { readonly kind: 'restored'; readonly row: Named }
  | { readonly kind: 'gone'; readonly name: string }

/** What the page says after a change to the list, and where focus goes next. */
export interface Board {
  readonly notice: Notice | null
  readonly problem: string | null
  readonly busy: { readonly id: string; readonly act: 'remove' | 'restore' } | null
  /** The id of the element to focus once it is on the page. Only the event that moves focus sets it. */
  readonly focus: string | null
}

export type BoardEvent =
  | { readonly type: 'added'; readonly name: string }
  | { readonly type: 'removing' | 'removed' | 'gone' | 'restoring' | 'restored'; readonly row: Named }
  | { readonly type: 'failed'; readonly words: string }
  | { readonly type: 'dismissed' }

export const EMPTY_BOARD: Board = { notice: null, problem: null, busy: null, focus: null }

export const UNDO_ID = 'undo-removal'

export const removeButtonId = (id: string) => `remove-${id}`

/** An Undo message has no time limit: it stays until the next message replaces it or the person dismisses it. */
export function board(state: Board, event: BoardEvent): Board {
  switch (event.type) {
    case 'added':
      return { ...state, notice: { kind: 'added', name: event.name }, problem: null, focus: null }
    case 'removing':
      return { notice: null, problem: null, busy: { id: event.row.id, act: 'remove' }, focus: null }
    case 'removed':
      return { notice: { kind: 'removed', row: event.row }, problem: null, busy: null, focus: UNDO_ID }
    case 'gone':
      return { notice: { kind: 'gone', name: event.row.name }, problem: null, busy: null, focus: null }
    case 'restoring':
      return { ...state, problem: null, busy: { id: event.row.id, act: 'restore' }, focus: null }
    case 'restored':
      return { notice: { kind: 'restored', row: event.row }, problem: null, busy: null, focus: removeButtonId(event.row.id) }
    case 'failed':
      return { ...state, problem: event.words, busy: null, focus: null }
    case 'dismissed':
      return { ...state, notice: null, focus: null }
  }
}

export function noticeWords(notice: Notice, scheduled: boolean): string {
  switch (notice.kind) {
    case 'added':
      return scheduled ? `Added ${notice.name}. It is checked at the next check.` : `Added ${notice.name}. Press Check now to check it.`
    case 'removed':
      return `Removed ${notice.row.name}. It won’t be checked any more.`
    case 'restored':
      return `Put ${notice.row.name} back on the list.`
    case 'gone':
      return `${notice.name} was already removed.`
  }
}

/** The callbacks a TanStack mutate takes, as far as these presses use them. */
export interface Outcome {
  onSuccess?: (value: unknown) => void
  onError?: (error: unknown) => void
  onSettled?: () => void
}

type Send = (id: string, outcome: Outcome) => void
type Words = (error: unknown) => string

const answered = (error: unknown, status: number) => error instanceof ApiError && error.status === status

function restoreProblem(name: string, error: unknown, words: Words): string {
  const start = `Could not put ${name} back.`
  if (answered(error, 409)) return `${start} Its repository was added again since, so it is on the list already.`
  if (answered(error, 404)) return `${start} The platform has no record of it.`
  if (answered(error, 422)) return `${start} The list is full. Remove software you no longer run, then try again.`
  return `${start} ${words(error)}`
}

/** Removes at once, so the list on the page is the list the platform checks. Undo puts the same entry back. */
export function pressRemove(latch: Latch, send: Send, row: Named, dispatch: (event: BoardEvent) => void, words: Words): void {
  latch.run((settled) => {
    dispatch({ type: 'removing', row })
    send(row.id, {
      onSuccess: () => dispatch({ type: 'removed', row }),
      onError: (error) => dispatch(answered(error, 404) ? { type: 'gone', row } : { type: 'failed', words: `Could not remove ${row.name}. ${words(error)}` }),
      onSettled: settled,
    })
  })
}

export function pressUndo(latch: Latch, send: Send, row: Named, dispatch: (event: BoardEvent) => void, words: Words): void {
  latch.run((settled) => {
    dispatch({ type: 'restoring', row })
    send(row.id, {
      onSuccess: () => dispatch({ type: 'restored', row }),
      onError: (error) => dispatch({ type: 'failed', words: restoreProblem(row.name, error, words) }),
      onSettled: settled,
    })
  })
}
