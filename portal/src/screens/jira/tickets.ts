import { ApiError } from '../../api/client'
import type { MockJiraTicket } from '../../api/types'
import { dateAndClock } from '../workflows/times'

export const JIRA_PATH = '/jira'
export const PRACTICE_NOTE = 'Practice copy of Jira. Nothing reaches a real Jira.'
export const EMPTY_WORDS = 'No tickets yet. When a run creates one after a yes, it shows here.'
export const LOAD_WORDS = 'The tickets could not be loaded.'

export const ticketPath = (key: string) => `${JIRA_PATH}/${key}`
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

export function splitKeys(words: string): Piece[] {
  const pieces: Piece[] = []
  let from = 0
  for (const match of words.matchAll(/(?<![A-Za-z0-9-])MOCK-\d+(?![A-Za-z0-9-])/g)) {
    if (match.index > from) pieces.push({ text: words.slice(from, match.index), key: false })
    pieces.push({ text: match[0], key: true })
    from = match.index + match[0].length
  }
  if (from < words.length) pieces.push({ text: words.slice(from), key: false })
  return pieces
}

export const doneWords = (key: string) => `${key} is Done. The Software watchlist has its new version.`
export const missingWords = (key: string) => `${key} is not in the practice Jira.`

export function markDoneProblem(error: unknown, key: string, words: (error: unknown) => string): string {
  if (error instanceof ApiError && error.status === 404) return `${key} is not in the practice Jira any more. The list is up to date now.`
  if (error instanceof ApiError && error.status === 403) return 'Only an Operator can mark a ticket Done. Ask an Operator to do it.'
  return `${key} is not Done yet. ${words(error)}`
}
