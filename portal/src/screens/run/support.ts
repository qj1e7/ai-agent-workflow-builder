import type { TeamRequestView } from '../../api/types'
import { withCurrentNames } from './words'

export const NOTE_ROOM = 500
/** What the platform keeps of a report's note. */
export const NOTE_LIMIT = 1000

export const FOLLOWING_UP_WORDS = 'Updates appear under Following up on Workflows.'

/** An agent's error starts with its type, as in "ModelNeeded: ". The type is a code name and means nothing to a reader. */
const ERROR_TYPE = /^[A-Z][A-Za-z0-9]*: /

/** The platform's own note about a stop, in the words the page uses elsewhere. The error type is a code name and means nothing to a reader. */
export function failureText(message: string): string {
  const text = message.trim().replace(ERROR_TYPE, '').trim()
  if (text === '') return ''
  return withCurrentNames(/[.!?…]$/.test(text) ? text : `${text}.`)
}

/** The most of a name the note's label carries. The label is not the person's own words, so a very long name must not push them out. */
const NAME_ROOM = 80

/**
 * The note the case carries: what the troubleshooter found, then the person's own words. Never longer than the
 * platform allows. When it would be, the troubleshooter's text is trimmed first and the person's words stay whole.
 */
export function reportNote(found: string, extra: string, name: string): string {
  const own = extra.trim().slice(0, NOTE_ROOM)
  if (own === '') return fit(found, NOTE_LIMIT)
  const label = `\n\nNote from ${name.length > NAME_ROOM ? `${name.slice(0, NAME_ROOM - 1).trimEnd()}…` : name}: `
  return `${fit(found, NOTE_LIMIT - label.length - own.length)}${label}${own}`
}

function fit(text: string, room: number): string {
  return text.length > room ? `${text.slice(0, room - 1).trimEnd()}…` : text
}

/** What the platform said about the card to the team's channel. It claims a delivery only when the platform did. */
export function deliveryWords(sent: Pick<TeamRequestView, 'posted_to_teams' | 'not_posted_because'>): string {
  if (sent.posted_to_teams) return 'It was also posted in the team’s Teams channel.'
  switch (sent.not_posted_because) {
    case 'posting':
      return 'It is still going to the team’s Teams channel.'
    case 'no_channel':
      return 'No Teams channel is set up, so the team will see it only in the app.'
    case 'failed':
      return 'Teams did not take it, so the team will see it only in the app.'
    default:
      return 'The team will see it in the app.'
  }
}
