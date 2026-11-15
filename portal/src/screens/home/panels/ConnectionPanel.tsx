import { useHome } from '../../../api/homeQueries'
import { ButtonLink } from '../../../ui/Button'
import { connectionWords } from '../../settings/connections'
import { onDay } from '../home'
import styles from './Lists.module.css'

export const CONNECTIONS_PATH = '/settings?tab=connections'

/** A connection’s name for a title: a key that is running out is the sketch’s “Jira key”, the rest keep their name. */
export const connectionTitle = (connection: { readonly name: string; readonly state: string; readonly expires_at: string | null }): string =>
  connection.state === 'working' && connection.expires_at ? `${connection.name} key` : connection.name

/**
 * A connection that needs the person, in the platform’s own words and as it is now (the sketch’s `key` view). It is read from Home’s
 * Needs you, so once the connection works again the panel says so instead of showing what no longer holds. Only Settings changes
 * a connection, so the button goes there. Nothing here claims a message to an admin the platform doesn’t send.
 */
export function ConnectionPanel({ id, now }: { id: string; now: Date }) {
  const home = useHome()
  if (!home.data) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read that connection just now.' : 'Checking the connection'}
      </p>
    )
  }
  const connection = home.data.connections.find((item) => item.id === id)
  if (!connection) return <p className={styles['calm']}>That connection doesn’t need anything from you now.</p>
  const words = connectionWords(connection, now)
  const pill = connection.state === 'working' && connection.expires_at ? `Expires ${onDay(connection.expires_at, now)}` : words.label
  return (
    <div className={styles['stack']}>
      <div className={styles['head']}>
        <p className={styles['kind']}>Connection</p>
        <span className={styles['pill']} data-tone={words.health === 'ok' ? 'good' : words.health === 'warn' ? 'wait' : undefined}>
          {pill}
        </span>
      </div>
      <p className={styles['sent']}>{words.text}</p>
      {words.checked ? <p className="muted">{words.checked}</p> : null}
      <div className={styles['actions']}>
        <ButtonLink to={CONNECTIONS_PATH}>See it in Settings</ButtonLink>
      </div>
    </div>
  )
}
