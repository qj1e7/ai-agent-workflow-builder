import { useId, useState, type ReactNode, type Ref } from 'react'
import { StepLog } from './Chat'
import { count, type LogRow } from './words'
import styles from './RunPage.module.css'

interface HistoryProps {
  /** The plain steps, built by code from the run's events. */
  readonly rows: readonly LogRow[]
  /** The agents' own words, for support. Behind "Show agent messages". */
  readonly messages: readonly LogRow[]
  readonly loadedUpTo: number
  readonly open: boolean
  readonly onToggle: (open: boolean) => void
  /** The run line, the live picture of the steps, drawn above the list. */
  readonly line?: ReactNode
  readonly listRef?: Ref<HTMLOListElement> | undefined
}

/**
 * "What happened (3 steps)", folded once the run needs the person or is over, and open while the agents work or the run is stopped.
 * The agents' own words stay one more click away, for support, so the AI's report is never read as the check or repeated as a step.
 */
export function History({ rows, messages, loadedUpTo, open, onToggle, line, listRef }: HistoryProps) {
  const [said, setSaid] = useState(false)
  const listId = useId()
  return (
    <section className={styles['history']}>
      <details open={open}>
        <summary
          onClick={(event) => {
            event.preventDefault()
            onToggle(!open)
          }}
        >
          What happened ({count(rows.length, 'step')})
        </summary>
        <div className={styles['historyBody']}>
          {line}
          <StepLog {...(listRef ? { ref: listRef } : {})} rows={rows} loadedUpTo={loadedUpTo} />
          {messages.length > 0 ? (
            <>
              <button type="button" className={styles['linkButton']} aria-expanded={said} aria-controls={listId} onClick={() => setSaid(!said)}>
                {said ? 'Hide agent messages' : 'Show agent messages'}
              </button>
              <div id={listId}>{said ? <StepLog rows={messages} loadedUpTo={loadedUpTo} label="Agent messages" /> : null}</div>
            </>
          ) : null}
        </div>
      </details>
    </section>
  )
}
