import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useRunClock, usePortalMode } from '../../api/context'
import { useRuns, useTemplates } from '../../api/queries'
import type { RunView } from '../../api/types'
import { ActorAvatar, Caption } from '../../room/Caption'
import { useLiveRoom, useReducedMotion, useWidth } from '../../room/hooks'
import { Legend } from '../../room/Legend'
import { clockTime } from '../../room/Minutes'
import { ActionCard, TroubleshooterPanel } from '../../room/NeedsYou'
import { Room } from '../../room/Room'
import { RunHead } from '../../room/RunHead'
import { expectedWritesOf, spineBlocks } from '../../room/spineBlocks'
import { Transport } from '../../room/Transport'
import { useBlocks } from '../../room/useBlocks'
import type { LiveView, WhenFinished } from '../../run'
import { ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime, formatRelative, formatTime } from '../../ui/format'
import { Spine, type SpineBlock } from '../../ui/Spine'
import { StatusPill } from '../../ui/StatusPill'
import { FirstRun } from './FirstRun'
import { runDots } from './runDots'
import styles from './OverviewPage.module.css'

const SETTLED = new Set<RunView['state']>(['succeeded', 'rejected', 'failed'])
/** The plan rises in 500 ms, three doors follow 60 ms apart, the room's contents land at 860 ms: the first beat waits this long. */
const OPENING_MS = 900
const SO_FAR = 3

/** The opening plays once per page load, on the first overview the person sees, never on a later navigation. */
let openedOnce = false

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
      {runs.data && !latest ? <FirstRun /> : null}
      {latest ? <Hero key={latest.run_id} run={latest} /> : null}
      {runs.data && runs.data.length > 1 ? <EarlierRuns runs={runs.data.slice(1)} /> : null}
    </div>
  )
}

function Hero({ run }: { run: RunView }) {
  // Decided once per run: a run that was already finished when the page opened replays, a live one is followed to its end.
  const [whenFinished] = useState<WhenFinished>(() => (SETTLED.has(run.state) ? 'replay' : 'rest'))
  const reduced = useReducedMotion()
  const [opening] = useState(() => {
    if (openedOnce || reduced) return false
    openedOnce = true
    return true
  })
  const view = useLiveRoom(run.run_id, whenFinished, opening ? OPENING_MS : 0)
  const blocks = useBlocks(run)
  const nameOf = useDisplayName()
  const mode = usePortalMode()
  const roomRef = useRef<HTMLDivElement>(null)
  const width = useWidth(roomRef)
  const { room, frame } = view
  // The pill follows the room's phase, the same source as the caption and the spine; the REST view speaks only before the first frame.
  const state = room.phase.name === 'empty' ? run.state : room.phase.name
  const startedBy = nameOf(run.started_by)
  const watching = frame.label === 'live' ? 'Watching the run as it happens.' : frame.label === 'replay' ? 'Replaying it from the start.' : 'Finished.'
  const needsYou = room.phase.name === 'failed' ? <TroubleshooterPanel runId={run.run_id} view={view} /> : room.phase.name === 'awaiting_approval' ? <ActionCard view={view} /> : null
  const spine: SpineBlock[] = spineBlocks(view, blocks)

  return (
    <section className={styles['hero']} aria-labelledby="hero-title">
      <RunHead
        titleId="hero-title"
        title={run.use_case_name}
        lede={`Started by ${startedBy} at ${formatTime(run.started_at)}. ${watching}${mode === 'demo' ? ' This is demo data.' : ''}`}
        state={state}
      />
      <div className={styles['heroBody']}>
        <div className={styles['stageColumn']}>
          <div ref={roomRef}>
            <Room view={view} width={width} expectedWrites={expectedWritesOf(blocks)} label={`The room for ${run.use_case_name}`} opening={opening} />
          </div>
          <Caption room={room} />
          <Transport view={view} />
          <Legend />
        </div>
        <aside className={styles['rail']} aria-label="Where the run is">
          {blocks ? <Spine blocks={spine} orientation="vertical" compact /> : null}
          {needsYou}
          <SoFar view={view} />
          <ButtonLink to={`/runs/${run.run_id}`}>Open the full run</ButtonLink>
        </aside>
      </div>
    </section>
  )
}

/** The last few story summaries, oldest first with the latest marked, in the same order as the run page's Minutes. */
function SoFar({ view }: { view: LiveView }) {
  const recent = view.minutes.filter((entry) => entry.tier === 'story').slice(-SO_FAR)
  return (
    <section className={styles['soFar']} aria-labelledby="so-far-title">
      <h2 id="so-far-title" className={styles['soFarTitle']}>
        So far
      </h2>
      {recent.length === 0 ? (
        <p className="muted">Nothing has happened yet.</p>
      ) : (
        <ol className={styles['soFarList']}>
          {recent.map((entry, index) => (
            <li key={entry.seq} className={cx(styles['soFarEntry'], index === recent.length - 1 && 'story-latest')} aria-current={index === recent.length - 1 ? 'true' : undefined}>
              <ActorAvatar actor={entry.actor} size={20} />
              <span className={cx(styles['soFarSummary'], 'story-summary')}>{entry.summary}</span>
              <time className={styles['soFarTime']} dateTime={new Date(entry.at).toISOString()}>
                {clockTime(entry.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
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
