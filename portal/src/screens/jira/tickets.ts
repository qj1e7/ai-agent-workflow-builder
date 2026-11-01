import { ApiError } from '../../api/client'
import { pressOnce, type Latch, type Outcome } from '../../api/latch'
import type { MockJiraTicket } from '../../api/types'
import { dateAndClock } from '../workflows/times'

export const JIRA_PATH = '/jira'
export const EMPTY_WORDS = 'No tickets yet. When a run creates one after a yes, it shows here.'
export const LOAD_WORDS = 'The tickets could not be loaded.'

export const ticketPath = (key: string) => `${JIRA_PATH}/${encodeURIComponent(key)}`
export const detailsId = (key: string) => `ticket-details-${key}`
export const createdWords = (iso: string) => `Created ${dateAndClock(iso)}`

export interface TicketHref {
  readonly href: string
  readonly external: boolean
}

/**
 * The one place that decides where a ticket key links. With a Jira address in /config.json it is the real Jira,
 * as an outside link. Without one it is the practice Jira page, open at that ticket.
 */
export function ticketHref(key: string, browseUrl: string | null): TicketHref {
  if (browseUrl === null || browseUrl === '') return { href: ticketPath(key), external: false }
  return {
    href: browseUrl.replaceAll('{key}', encodeURIComponent(key)),
    external: true,
  }
}

const number = (key: string) => Number(key.slice(key.lastIndexOf('-') + 1)) || 0

export function newestFirst(tickets: readonly MockJiraTicket[]): MockJiraTicket[] {
  return [...tickets].sort((a, b) => b.created_at.localeCompare(a.created_at) || number(b.key) - number(a.key))
}

export function showMarkDone(ticket: MockJiraTicket, operator: boolean): boolean {
  return operator && ticket.status !== 'Done'
}

export interface Piece {
  readonly text: string
  readonly key: boolean
}

/** Splits words on exactly these ticket keys. It never guesses at what looks like a key, so UTF-8 and CVE-2024-1234 stay words. */
export function splitKeys(words: string, keys: readonly string[]): Piece[] {
  if (keys.length === 0) return words === '' ? [] : [{ text: words, key: false }]
  const escaped = [...new Set(keys)].sort((a, b) => b.length - a.length).map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(?<![A-Za-z0-9-])(?:${escaped.join('|')})(?![A-Za-z0-9-])`, 'g')
  const pieces: Piece[] = []
  let from = 0
  for (const match of words.matchAll(pattern)) {
    if (match.index > from) pieces.push({ text: words.slice(from, match.index), key: false })
    pieces.push({ text: match[0], key: true })
    from = match.index + match[0].length
  }
  if (from < words.length) pieces.push({ text: words.slice(from), key: false })
  return pieces
}

export const doneWords = (key: string) => `${key} is Done.`
export const missingWords = (key: string) => `${key} is not in the practice Jira.`

export function markDoneProblem(error: unknown, key: string, words: (error: unknown) => string): string {
  if (error instanceof ApiError && error.status === 404) return `${key} is not in the practice Jira any more. The list is up to date now.`
  if (error instanceof ApiError && error.status === 403) return 'Only an Operator can mark a ticket Done. Ask an Operator to do it.'
  return `${key} is not Done yet. ${words(error)}`
}

export interface MarkDoneUi {
  readonly start: () => void
  /** Asks for focus to move to the ticket's Details button once the row reads Done, since Mark done is gone by then. */
  readonly armFocus: () => void
  readonly done: (said: string) => void
  readonly fail: (said: string) => void
  readonly settled: () => void
}

/** One press of Mark done: one request at a time, and each answer in plain words. */
export function pressMarkDone(latch: Latch, mark: (key: string, outcome: Outcome<unknown>) => void, key: string, ui: MarkDoneUi, words: (error: unknown) => string): void {
  ui.start()
  pressOnce<unknown>(latch, (outcome) => mark(key, outcome), {
    onSuccess: () => {
      ui.armFocus()
      ui.done(doneWords(key))
    },
    onError: (error) => ui.fail(markDoneProblem(error, key, words)),
    onSettled: ui.settled,
  })
}
