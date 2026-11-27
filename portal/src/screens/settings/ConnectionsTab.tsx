import { useCapabilities, useCheckConnection, useConnections } from '../../api/capabilityQueries'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import type { CapabilityView, ConnectionOut, TellSetupOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { AlertMark, CheckMark, SystemMark } from './marks'
import { cardsOf, CHECK_DOWN_WORDS, type Health, checkResultWords, connectionWords, GITHUB_KEY_NOTE, keyWords, TEAMS_DOES_WORDS, TELL_CHANGED_BY_WORDS, tellWords, usedBy } from './connections'
import { ONLY_OPERATORS_WORDS } from './settings'
import styles from './Settings.module.css'

function CheckNow({ connection, describedBy }: { connection: ConnectionOut; describedBy: string | undefined }) {
  const check = useCheckConnection(connection.id)
  const latch = useLatch()
  const words = useErrorWords()
  const press = () => latch.run((settled) => check.mutate(undefined, { onSettled: settled }))
  return (
    <>
      <div className={styles['buttons']}>
        <Button loading={check.isPending} onClick={press} aria-describedby={describedBy}>
          Check now
          <span className="visually-hidden"> for {connection.name}</span>
        </Button>
      </div>
      {check.isError ? (
        <p className={styles['error']} role="alert">
          <AlertMark />
          <span>
            {CHECK_DOWN_WORDS} {words(check.error)}
          </span>
        </p>
      ) : check.isSuccess ? (
        <p className={styles['small']} role="status">
          {checkResultWords(check.data)}
        </p>
      ) : null}
    </>
  )
}

interface CardProps {
  readonly connection: ConnectionOut
  readonly capabilities: readonly CapabilityView[] | undefined
  readonly canCheck: boolean
  readonly now: Date
}

function ConnectionCard({ connection, capabilities, canCheck, now }: CardProps) {
  const says = connectionWords(connection, now)
  const used = capabilities ? usedBy(connection.id, capabilities) : null
  const key = keyWords(connection)
  const textId = `connection-${connection.id}-says`
  // A connection that works says so in its pill. Its sentence is only for one that has something to say.
  const sentence = connection.state === 'working' ? null : says.text
  return (
    <article className={styles['connection']} data-connection={connection.id} data-state={connection.state}>
      <div className={styles['connectionTop']}>
        <span className={styles['sys']} aria-hidden="true">
          <SystemMark id={connection.id} />
        </span>
        <div className={styles['connectionName']}>
          <h3>{connection.name}</h3>
          {says.checked ? <p className={styles['when']}>{says.checked}</p> : null}
        </div>
        <span className={styles['tags']}>
          {connection.practice ? <span className={styles['tag']}>Practice copy</span> : null}
          <span className={styles['pill']} data-tone={DOT[says.health]}>
            {says.health === 'ok' ? <CheckMark /> : says.health === 'warn' ? <AlertMark /> : null}
            {says.label}
          </span>
        </span>
      </div>
      {sentence ? <p id={textId}>{sentence}</p> : null}
      {connection.id === 'github' && says.checked ? <p className={styles['small']}>{GITHUB_KEY_NOTE}</p> : null}
      <dl className={styles['facts']}>
        {connection.id === 'teams' ? (
          <div>
            <dt>What it does</dt>
            <dd>{TEAMS_DOES_WORDS}</dd>
          </div>
        ) : null}
        <div>
          <dt>What uses it</dt>
          <dd>
            {used === null ? (
              'Not available right now'
            ) : used.length > 0 ? (
              <ul>
                {used.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              'Nothing yet'
            )}
          </dd>
        </div>
        {key ? (
          <div>
            <dt>Key</dt>
            <dd>{key}</dd>
          </div>
        ) : null}
      </dl>
      {says.note ? (
        <p className={styles['callout']}>
          <AlertMark />
          <span>{says.note}</span>
        </p>
      ) : null}
      {canCheck && connection.state !== 'not_set_up' ? <CheckNow connection={connection} describedBy={sentence ? textId : undefined} /> : null}
    </article>
  )
}

function TellCard({ tell }: { tell: TellSetupOut }) {
  const says = tellWords(tell)
  return (
    <article className={styles['connection']} data-connection="tell">
      <div className={styles['connectionTop']}>
        <span className={styles['sys']} aria-hidden="true">
          <SystemMark id="tell" />
        </span>
        <div className={styles['connectionName']}>
          <h3>Tell flow</h3>
        </div>
        <span className={styles['tags']}>
          <span className={styles['pill']} data-tone="off">
            {says.label}
          </span>
        </span>
      </div>
      <p>{says.text}</p>
      <dl className={styles['facts']}>
        <div>
          <dt>Posts in</dt>
          <dd>{tell.channel}</dd>
        </div>
        <div>
          <dt>Emails</dt>
          <dd>{says.emails}</dd>
        </div>
        <div>
          <dt>Who changes these</dt>
          <dd>{TELL_CHANGED_BY_WORDS}</dd>
        </div>
      </dl>
    </article>
  )
}

const DOT: Record<Health, string> = { ok: 'ok', warn: 'wait', off: 'off' }

/** One finding first: how many of the connections work, with a dot for each. Count, dots and card pills all come from connectionWords. */
function Summary({ connections, now }: { connections: readonly ConnectionOut[]; now: Date }) {
  const says = connections.map((connection) => connectionWords(connection, now))
  const working = says.filter((s) => s.label === 'Working').length
  return (
    <p className={styles['health']}>
      <span className={styles['hdots']} aria-hidden="true">
        {connections.map((connection, index) => (
          <i key={connection.id} data-tone={DOT[says[index]?.health ?? 'off']} />
        ))}
      </span>
      <span>
        <b>
          {working} of {connections.length} working.
        </b>{' '}
        A check only reads, so it never changes anything.
      </span>
    </p>
  )
}

export function ConnectionsTab({ now }: { now: Date }) {
  const connections = useConnections()
  const capabilities = useCapabilities()
  const words = useErrorWords()
  if (connections.isPending) {
    return (
      <p className="muted" role="status">
        Loading
      </p>
    )
  }
  if (connections.isError) {
    return (
      <section className={styles['panel']} aria-labelledby="connections-heading">
        <h2 id="connections-heading" className="visually-hidden">
          Connections
        </h2>
        <p role="alert">Connections are not available right now. {words(connections.error)}</p>
        <div className={styles['buttons']}>
          <Button onClick={() => void connections.refetch()}>Try again</Button>
        </div>
      </section>
    )
  }
  const { you_can_check: canCheck } = connections.data
  return (
    <section className={`${styles['panel']} ${styles['connectionsPanel']}`} aria-labelledby="connections-heading">
      <h2 id="connections-heading" className="visually-hidden">
        Connections
      </h2>
      <Summary connections={cardsOf(connections.data.connections)} now={now} />
      <div className={styles['connections']}>
        {cardsOf(connections.data.connections).map((connection) => (
          <ConnectionCard key={connection.id} connection={connection} capabilities={capabilities.data?.capabilities} canCheck={canCheck} now={now} />
        ))}
        <TellCard tell={connections.data.tell} />
      </div>
      {canCheck ? null : <p className={styles['note']}>{ONLY_OPERATORS_WORDS}</p>}
    </section>
  )
}
