import { useState } from 'react'
import { Link } from 'react-router'
import { useErrorWords, useRunClock } from '../../api/context'
import { useDisplayName } from '../../api/people'
import { useRuns, useTemplates } from '../../api/queries'
import type { RunView } from '../../api/types'
import { useLiveRun } from '../../tracker/hooks'
import { Tracker } from '../../tracker/Tracker'
import { useRunTemplate } from '../../tracker/useRunTemplate'
import type { WhenFinished } from '../../run'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime, formatRelative } from '../../ui/format'
import { StatusPill } from '../../ui/StatusPill'
import { FirstRun } from './FirstRun'
import { runDots } from './runDots'
import styles from './OverviewPage.module.css'

const SETTLED = new Set<RunView['state']>(['succeeded', 'rejected', 'failed'])

export function OverviewPage() {
  const explain = useErrorWords()
  const runs = useRuns({ poll: true })
  const latest = runs.data?.[0]
  return (
    <div className={`page ${styles['page']}`}>
      {runs.isError ? (
        <>
          <h1>Runs</h1>
          <InlineMessage tone="error">{explain(runs.error)}</InlineMessage>
        </>
      ) : null}
      {runs.isPending ? (
        <>
          <h1>Runs</h1>
          <Skeleton lines={4} label="Loading the latest run." />
        </>
      ) : null}
      {runs.data && !latest ? <FirstRun /> : null}
      {latest ? <Hero key={latest.run_id} run={latest} /> : null}
      {runs.data && runs.data.length > 1 ? <EarlierRuns runs={runs.data.slice(1)} /> : null}
    </div>
  )
}

function Hero({ run }: { run: RunView }) {
  // Decided once per run: a run that was already finished when the page opened replays, a live one is followed to its end.
  const [whenFinished] = useState<WhenFinished>(() => (SETTLED.has(run.state) ? 'replay' : 'rest'))
  const view = useLiveRun(run.run_id, whenFinished)
  const template = useRunTemplate(run)
  return <Tracker runId={run.run_id} view={view} template={template} title={run.use_case_name} titleTo={`/runs/${run.run_id}`} />
}

function EarlierRuns({ runs }: { runs: readonly RunView[] }) {
  const nameOf = useDisplayName()
  const clock = useRunClock()
  const templates = useTemplates()
  return (
    <section className={styles['earlier']} aria-labelledby="earlier-title">
      <h2 id="earlier-title">Earlier runs</h2>
      <ul className={styles['rows']}>
        {runs.map((run) => {
          const dots = runDots(run, templates.data)
          return (
            <li key={run.run_id}>
              <Link to={`/runs/${run.run_id}`} className={styles['row']}>
                <span className={styles['rowName']}>{run.use_case_name}</span>
                <StatusPill state={run.state} />
                <span className={styles['rowMeta']}>
                  Started by {nameOf(run.started_by)}, {formatRelative(run.started_at, clock.now(run.run_id)).toLowerCase()}
                  <span className="visually-hidden"> on {formatDayAndTime(run.started_at)}</span>
                </span>
                <span className={styles['dots']} aria-label={dots.map((dot) => `${dot.name}: ${dot.words}`).join('. ')}>
                  {dots.map((dot) => (
                    <span key={dot.key} className={`${styles['dot']} ${styles[`dot_${dot.state}`] ?? ''}`} aria-hidden="true" />
                  ))}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
