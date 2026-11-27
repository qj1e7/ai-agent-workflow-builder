import { useCapabilities, useCheckConnection, useConnections } from '../../api/capabilityQueries'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import type { CapabilityView, ConnectionOut, TellSetupOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { AlertMark, CheckMark } from './marks'
import { cardsOf, CHECK_DOWN_WORDS, checkResultWords, connectionWords, GITHUB_KEY_NOTE, keyWords, TEAMS_DOES_WORDS, TELL_CHANGED_BY_WORDS, tellWords, usedBy } from './connections'
import { ONLY_OPERATORS_WORDS } from './settings'
import styles from './Settings.module.css'

function CheckNow({ connection, describedBy }: { connection: ConnectionOut; describedBy: string }) {
  const check = useCheckConnection(connection.id)
  const latch = useLatch()
  const words = useErrorWords()
  const press = () => latch.run((settled) => check.mutate(undefined, { onSettled: settled }))
  return (
    <>
      <div className={styles['buttons']}>
        <Button variant={connection.state === 'working' ? 'secondary' : 'primary'} loading={check.isPending} onClick={press} aria-describedby={describedBy}>
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
  return (
    <article className={styles['connection']} data-connection={connection.id} data-state={connection.state}>
      <div className={styles['connectionTop']}>
        <h3>{connection.name}</h3>
        {connection.practice ? <span className={styles['tag']}>Practice copy</span> : null}
        <span className={styles['pill']} data-tone={says.health}>
          {says.health === 'ok' ? <CheckMark /> : says.health === 'warn' ? <AlertMark /> : null}
          {says.label}
        </span>
      </div>
      <p id={textId}>
        {says.text}
        {says.checked ? <span className={styles['small']}> {says.checked}.</span> : null}
      </p>
      {connection.id === 'github' && says.checked ? <p className={styles['small']}>{GITHUB_KEY_NOTE}</p> : null}
      <dl className={styles['facts']}>
        {connection.id === 'teams' ? (
          <>
            <dt>What it does</dt>
            <dd>{TEAMS_DOES_WORDS}</dd>
          </>
        ) : null}
        <dt>What uses it</dt>
        <dd>{used === null ? 'Not available right now' : used.length > 0 ? used.join('; ') : 'Nothing yet'}</dd>
        {key ? (
          <>
            <dt>Key</dt>
            <dd>{key}</dd>
          </>
        ) : null}
      </dl>
      {canCheck && connection.state !== 'not_set_up' ? <CheckNow connection={connection} describedBy={textId} /> : null}
    </article>
  )
}

function TellCard({ tell }: { tell: TellSetupOut }) {
  const says = tellWords(tell)
  return (
    <article className={styles['connection']} data-connection="tell">
      <div className={styles['connectionTop']}>
        <h3>Tell flow</h3>
        <span className={styles['pill']} data-tone="off">
          {says.label}
        </span>
      </div>
      <p>{says.text}</p>
      <dl className={styles['facts']}>
        <dt>Posts in</dt>
        <dd>{tell.channel}</dd>
        <dt>Emails</dt>
        <dd>{says.emails}</dd>
        <dt>Who changes these</dt>
        <dd>{TELL_CHANGED_BY_WORDS}</dd>
      </dl>
    </article>
  )
}

const dotTone = (connection: ConnectionOut) =>
  connection.state === 'working' ? (connection.expires_at ? 'wait' : 'ok') : connection.state === 'not_checked' || connection.state === 'not_set_up' ? 'off' : 'wait'

/** One finding first: how many of the connections work, with a dot for each. A key that runs out soon still works, so it counts as working but shows amber. */
function Summary({ connections }: { connections: readonly ConnectionOut[] }) {
  const working = connections.filter((connection) => connection.state === 'working').length
  return (
    <p className={styles['health']}>
      <span className={styles['hdots']} aria-hidden="true">
        {connections.map((connection) => (
          <i key={connection.id} data-tone={dotTone(connection)} />
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
    <section className={styles['panel']} aria-labelledby="connections-heading">
      <h2 id="connections-heading" className="visually-hidden">
        Connections
      </h2>
      <Summary connections={cardsOf(connections.data.connections)} />
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
