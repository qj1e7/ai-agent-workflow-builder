import type { ReactNode, Ref } from 'react'
import { agentIdentity } from '../../ui/agents'
import { cx } from '../../ui/cx'
import { usePauseUnseen } from '../../ui/loops'
import { TicketKeys } from '../jira/TicketKeys'
import type { LogRow } from './words'
import styles from './Chat.module.css'

/** Past this many rows the log folds behind a button, as the plan keeps a disclosure only for a long log. */
export const LONG_LOG = 12

/**
 * The run page's Step by step (the sketch's `.log`): one row for each thing that happened, the time to the second and one sentence.
 * No bubbles. An agent's own words carry its name in its colour. A row the gate's decision landed on takes focus.
 */
export function StepLog({ rows, loadedUpTo, ref }: { rows: readonly LogRow[]; loadedUpTo: number; ref?: Ref<HTMLOListElement> }) {
  const pauseUnseen = usePauseUnseen()
  return (
    <div ref={pauseUnseen}>
      <ol className={styles['log']} aria-label="Step by step" ref={ref}>
        {rows.map((row) => (
          <li
            key={row.seq}
            className={cx(row.tone === 'bad' && styles['bad'], row.tone === 'wait' && styles['wait'], row.seq > loadedUpTo && styles['in'])}
            tabIndex={row.gate ? -1 : undefined}
            data-gate-said={row.gate ? row.seq : undefined}
          >
            <time className={styles['t']} dateTime={new Date(row.at).toISOString()}>
              {row.time}
            </time>
            <span>
              {row.agent ? (
                <b className={styles['who']} style={{ color: agentIdentity(row.agent.id, row.agent.display).hue }}>
                  {row.agent.display}{' '}
                </b>
              ) : null}
              <TicketKeys text={row.text} keys={row.keys} hrefs={row.urls} />
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export const DECISION_ID = 'decision'

/** The one place the run asks for the person, kept above the log: the gate's request, or the stop's answers. */
export function DecisionArea({ children, label }: { children: ReactNode; label: string }) {
  return (
    <section className={styles['decision']} id={DECISION_ID} tabIndex={-1} aria-label={label}>
      {children}
    </section>
  )
}
