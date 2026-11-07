import { Link } from 'react-router'
import { useCapabilities, useConnections } from '../../api/capabilityQueries'
import type { CapabilityView, CardView, ConnectionOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { AlertMark, CheckMark } from '../settings/marks'
import { CAPABILITIES_FOOT, CAPABILITIES_UNAVAILABLE_WORDS, capabilityNote, fieldsNote, GROUPS, groupOf, NOT_YET_QUESTION, settingsPathFor, type Group } from './capabilities'
import styles from './AgentsPage.module.css'

function Line({ capability, cards, connections, now }: { capability: CapabilityView; cards: readonly CardView[] | undefined; connections: readonly ConnectionOut[] | undefined; now: Date }) {
  const note = capabilityNote(capability, cards, now)
  const fields = fieldsNote(capability)
  return (
    <li className={styles['capRow']} data-capability={capability.id} data-state={capability.state}>
      <b>{capability.plain}</b>
      {note ? <span className={styles['small'] + ' muted'}>{note}</span> : null}
      {fields ? <span className={styles['small'] + ' muted'}>{fields}</span> : null}
      {capability.state === 'needs_setup' || capability.state === 'down' ? (
        <Link className={styles['small']} to={settingsPathFor(capability, connections)}>
          Open Settings<span className="visually-hidden"> for {capability.plain}</span>
        </Link>
      ) : null}
    </li>
  )
}

function Mark({ group }: { group: Group }) {
  return group === 'ready' ? <CheckMark /> : group === 'not_yet' ? null : <AlertMark />
}

export function CapabilitiesTab({ cards, now }: { cards: readonly CardView[] | undefined; now: Date }) {
  const capabilities = useCapabilities()
  const connections = useConnections().data?.connections
  if (capabilities.isPending) {
    return (
      <p className="muted" role="status">
        Loading
      </p>
    )
  }
  if (capabilities.isError) {
    return (
      <p className={styles['notice']} role="status">
        {CAPABILITIES_UNAVAILABLE_WORDS} <Button onClick={() => void capabilities.refetch()}>Try again</Button>
      </p>
    )
  }
  const all = capabilities.data.capabilities
  return (
    <>
      {GROUPS.map(({ id, title }) => {
        const list = all.filter((capability) => groupOf(capability.state) === id)
        if (list.length === 0) return null
        const lines = (
          <ul className={styles['capList']}>
            {list.map((capability) => (
              <Line key={capability.id} capability={capability} cards={cards} connections={connections} now={now} />
            ))}
          </ul>
        )
        return id === 'not_yet' ? (
          <details key={id} className={styles['fold']}>
            <summary>{NOT_YET_QUESTION}</summary>
            {lines}
          </details>
        ) : (
          <section key={id} className={styles['section']} aria-labelledby={`cap-${id}`}>
            <h2 id={`cap-${id}`}>
              <span className={styles['capMark']}>
                <Mark group={id} />
              </span>
              {title} <span className={styles['count']}>{list.length}</span>
            </h2>
            {lines}
          </section>
        )
      })}
      <p className={styles['small'] + ' muted'}>{CAPABILITIES_FOOT}</p>
    </>
  )
}
