import type { CapabilityView, ConnectionId, ConnectionOut } from '../../api/types'
import { runWhen } from '../workflows/times'

export type Health = 'ok' | 'warn' | 'off'

export interface ConnectionWords {
  readonly label: string
  readonly health: Health
  readonly text: string
  /** When the result shown was found, in words. Null when nothing has been tried with the address and key in use now. */
  readonly checked: string | null
}

/** The ones that have their own card here. The AI model has its own tab. */
export const cardsOf = (connections: readonly ConnectionOut[]) => connections.filter((connection) => connection.id !== 'model')

const SAYS: Record<Exclude<ConnectionOut['state'], 'working' | 'not_checked'>, { label: string; health: Health }> = {
  needs_attention: { label: 'Needs attention', health: 'warn' },
  not_answering: { label: 'Not working right now', health: 'warn' },
  not_set_up: { label: 'Not set up', health: 'warn' },
}

/** "Today, 9:00" reads "today, 9:00" in the middle of a sentence. */
const when = (iso: string, now: Date) => runWhen(iso, now).replace(/^Today/, 'today')

const dot = (words: string) => (/[.!?]$/.test(words) ? words : `${words}.`)

/** Words for a connection from the state the platform found. The text is the platform's own plain words, not a guess. */
export function connectionWords(connection: ConnectionOut, now: Date): ConnectionWords {
  const checked = connection.checked_at ? `Checked ${when(connection.checked_at, now)}` : null
  const fix = connection.fix ? ` ${dot(connection.fix)}` : ''
  const problem = dot(connection.problem ?? `${connection.name} needs attention.`)
  if (connection.state === 'working') {
    return connection.expires_at
      ? { label: 'Key running out', health: 'warn', text: `${problem}${fix}`, checked }
      : { label: 'Working', health: 'ok', text: `${connection.name} is working.`, checked }
  }
  if (connection.state === 'not_checked') {
    return { label: 'Not checked', health: 'off', text: dot(connection.problem ?? `${connection.name} has not been checked yet.`), checked }
  }
  const last = connection.state === 'not_answering' && connection.last_ok_at ? ` Last seen working ${when(connection.last_ok_at, now)}.` : ''
  return { ...SAYS[connection.state], text: `${problem}${last}${fix}`, checked }
}

/** What a Check now found, said from the answer's own state so a check that tried nothing never reads as a test. */
export function checkResultWords(found: ConnectionOut): string {
  if (found.state === 'working') return `Checked just now. ${found.name} answered.`
  if (found.state === 'not_checked') return dot(found.problem ?? 'Nothing was tried.')
  return `Checked just now. ${dot(found.problem ?? `${found.name} is not working.`)}`
}

export const GITHUB_KEY_NOTE = 'If the key was changed, this result is from before. It is read again at the next check.'

export function keyWords(connection: ConnectionOut): string | null {
  return connection.key_ends_in ? `Ends in ${connection.key_ends_in}` : null
}

/** The capabilities that cannot work without it, from the registry. The ones the platform has not built are not listed. */
export function usedBy(id: ConnectionId, capabilities: readonly CapabilityView[]): readonly string[] {
  return capabilities.filter((c) => c.connection === id && c.state !== 'planned' && c.state !== 'unsupported').map((c) => c.plain)
}

export const CHECK_DOWN_WORDS = 'Could not check.'

/** A connection that wants someone, shown as a dot on the tab. A key that runs out soon counts. */
export function connectionNeedsYou(connections: readonly ConnectionOut[] | undefined): boolean {
  return cardsOf(connections ?? []).some((c) => (c.state !== 'working' && c.state !== 'not_checked') || c.expires_at !== null)
}
