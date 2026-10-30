import { useId, useState } from 'react'
import { Link } from 'react-router'
import { starterName } from '../../api/labels'
import type { RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconChevronRight } from '../../ui/icons'
import { runFact, runWhen } from './workflow'
import styles from './Workflows.module.css'

export const RECENT_LIMIT = 10

interface RecentRunsProps {
  /** The workflow's runs, newest first. */
  readonly runs: readonly RunView[]
  readonly now: Date
  readonly nameOf: (id: string) => string
  /** When the first run is due, for a workflow that has not run yet, or null. */
  readonly firstRun: string | null
}

export function RecentRuns({ runs, now, nameOf, firstRun }: RecentRunsProps) {
  const [all, setAll] = useState(false)
  const headingId = useId()
  const shown = all ? runs : runs.slice(0, RECENT_LIMIT)
  const older = runs.length - shown.length
  return (
    <section className={styles['panel']} aria-labelledby={headingId}>
      <h2 id={headingId}>Recent runs</h2>
      {runs.length === 0 ? (
        <p className="muted">No runs yet.{firstRun ? ` The first one is ${firstRun}.` : ''}</p>
      ) : (
        <ul className={styles['runs']}>
          {shown.map((run) => (
            <li key={run.run_id} data-run-id={run.run_id} data-state={run.state}>
              <Link to={`/runs/${run.run_id}`} className={styles['runLink']}>
                <span>
                  <b>{runWhen(run.started_at, now)}</b>
                  <span>{runFact(run, nameOf).words}</span>
                  <span>Started by {starterName(nameOf(run.started_by), run.trigger)}</span>
                </span>
                <span className={styles['open']}>
                  Open
                  <IconChevronRight size={16} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {older > 0 ? (
        <div>
          <Button onClick={() => setAll(true)}>Show {older} older {older === 1 ? 'run' : 'runs'}</Button>
        </div>
      ) : null}
    </section>
  )
}
