import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useRunClock, usePortalMode } from '../../api/context'
import { useRuns, useTemplates } from '../../api/queries'
import type { RunView } from '../../api/types'
import { Caption } from '../../room/Caption'
import { useLiveRoom, useWidth } from '../../room/hooks'
import { Legend } from '../../room/Legend'
import { ActionCard, TroubleshooterPanel } from '../../room/NeedsYou'
import { SpeechCard } from '../../room/pieces'
import { Room } from '../../room/Room'
import { expectedWritesOf, spineBlocks } from '../../room/spineBlocks'
import { Transport } from '../../room/Transport'
import { useBlocks } from '../../room/useBlocks'
import { ROOM_METRICS, type WhenFinished } from '../../run'
import { agentIdentity } from '../../ui/agents'
import { ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime, formatRelative, formatTime } from '../../ui/format'
import { IconArrow } from '../../ui/icons'
import { Spine, type SpineBlock } from '../../ui/Spine'
import { StatusPill } from '../../ui/StatusPill'
import { runDots } from './runDots'
import styles from './OverviewPage.module.css'

const SETTLED = new Set<RunView['state']>(['succeeded', 'rejected', 'failed'])

export function OverviewPage() {
  const runs = useRuns({ poll: true })
  const latest = runs.data?.[0]
  return (
    <div className="page">
      {runs.isError ? (
        <>
          <h1>Runs</h1>
          <InlineMessage tone="error">{errorWords(runs.error)}</InlineMessage>
        </>
      ) : null}
      {runs.isPending ? (
        <>
          <h1>Runs</h1>
          <Skeleton lines={4} label="Loading the latest run." />
        </>
      ) : null}
      {runs.data && !latest ? (
        <>
          <h1>Runs</h1>
          <EmptyState title="No runs yet" action={<ButtonLink to="/builder" variant="primary">Open the builder</ButtonLink>}>
            Describe a task in the builder and run it. The run shows up here as a room.
          </EmptyState>
        </>
      ) : null}
      {latest ? <Hero key={latest.run_id} run={latest} /> : null}
      {runs.data && runs.data.length > 1 ? <EarlierRuns runs={runs.data.slice(1)} /> : null}
    </div>
  )
}

function Hero({ run }: { run: RunView }) {
  // Decided once per run: a run that was already finished when the page opened replays, a live one is followed to its end.
  const [whenFinished] = useState<WhenFinished>(() => (SETTLED.has(run.state) ? 'replay' : 'rest'))
  const view = useLiveRoom(run.run_id, whenFinished)
  const blocks = useBlocks(run)
  const nameOf = useDisplayName()
  const mode = usePortalMode()
  const roomRef = useRef<HTMLDivElement>(null)
  const width = useWidth(roomRef)
  const compact = width > 0 && width < ROOM_METRICS.wide.minWidth
  const { room, frame } = view
  const state = room.phase.name === 'empty' ? run.state : room.phase.name
  const startedBy = nameOf(run.started_by)
  const watching = frame.label === 'live' ? 'Watching the run as it happens.' : frame.label === 'replay' ? 'Replaying it from the start.' : 'Finished.'
  const needsYou = room.phase.name === 'failed' ? <TroubleshooterPanel runId={run.run_id} view={view} /> : room.phase.name === 'awaiting_approval' ? <ActionCard view={view} /> : null
  const spine: SpineBlock[] = spineBlocks(view, blocks)

  return (
    <section className={styles['hero']} aria-labelledby="hero-title">
      <header className={styles['heroHead']}>
        <div className={styles['heroWords']}>
          <h1 id="hero-title" className={styles['heroTitle']}>
            {run.use_case_name}
          </h1>
          <p className={styles['heroLede']}>
            Started by {startedBy} at {formatTime(run.started_at)}. {watching}
            {mode === 'demo' ? ' This is demo data.' : ''}
          </p>
        </div>
        <StatusPill state={state} />
      </header>
      <div className={styles['heroBody']}>
        <div className={styles['stageColumn']}>
          <div ref={roomRef}>
            <Room view={view} width={width} expectedWrites={expectedWritesOf(blocks)} label={`The room for ${run.use_case_name}`} />
          </div>
          {compact && room.speech ? <SpeechCard speech={room.speech} speakerName={agentIdentity(room.speech.speaker).name} variant="slot" /> : null}
          <Caption room={room} />
          <Transport view={view} />
          <Legend />
        </div>
        <aside className={styles['rail']} aria-label="Where the run is">
          {blocks ? <Spine blocks={spine} orientation="vertical" compact /> : null}
          {needsYou}
          <Link to={`/runs/${run.run_id}`} className={styles['fullRun']}>
            Open the full run
            <IconArrow size={18} />
          </Link>
        </aside>
      </div>
    </section>
  )
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
                  Started by {nameOf(run.started_by)}, {formatRelative(run.started_at, clock(run.run_id)).toLowerCase()}
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
