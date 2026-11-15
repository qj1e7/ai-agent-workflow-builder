import { useId, useState } from 'react'
import { Link } from 'react-router'
import type { RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { stageWords } from '../run/words'
import { RunPill } from './Status'
import { runWhen, stageOfRun } from './workflow'
import styles from './Workflows.module.css'

export const RECENT_LIMIT = 10

interface RecentRunsProps {
  /** The workflow's runs, newest first. */
  readonly runs: readonly RunView[]
  readonly now: Date
  readonly nameOf: (id: string) => string
  readonly firstRun: string | null
}

/** Recent runs, as the sketch draws them: the day and time, where the run stands, its pill, and Open. Each row is one link of 44 px or more. */
export function RecentRuns({ runs, now, nameOf, firstRun }: RecentRunsProps) {
  const [all, setAll] = useState(false)
  const headingId = useId()
  const shown = all ? runs : runs.slice(0, RECENT_LIMIT)
  const older = runs.length - shown.length
  return (
    <section className={styles['section']} aria-labelledby={headingId}>
      <h2 id={headingId}>Recent runs</h2>
      <ul className={styles['rows']}>
        {runs.length === 0 ? (
          <li className={styles['plainRow']}>
            <span className={styles['main']}>
              <b>No runs yet</b>
              {firstRun ? <span className={styles['sub']}>First run {firstRun}.</span> : null}
            </span>
          </li>
        ) : (
          shown.map((run) => {
            const stage = stageOfRun(run)
            return (
              <li key={run.run_id} data-run-id={run.run_id} data-state={run.state}>
                <Link to={`/runs/${run.run_id}`} className={styles['runLink']}>
                  <span className={styles['main']}>
                    <b>{runWhen(run.started_at, now)}</b>
                    <span className={styles['sub']}>{stageWords(stage, nameOf)}</span>
                  </span>
                  <RunPill facts={stage} />
                  <span className={styles['open']}>Open</span>
                </Link>
              </li>
            )
          })
        )}
      </ul>
      {older > 0 ? (
        <div>
          <Button onClick={() => setAll(true)}>Show {older} older {older === 1 ? 'run' : 'runs'}</Button>
        </div>
      ) : null}
    </section>
  )
}
