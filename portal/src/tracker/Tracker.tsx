import { useCallback, useId, useRef } from 'react'
import { Link } from 'react-router'
import type { BlockView } from '../api/types'
import { attemptWords, headlineWords, type Headline, type LiveView, type Speed } from '../run'
import { useDecision } from '../screens/approval/useDecision'
import { cx } from '../ui/cx'
import { Skeleton } from '../ui/Feedback'
import { IconCheck, IconPause, IconSpinner, IconX } from '../ui/icons'
import { useReducedMotion } from './hooks'
import { ApprovalPanel, TroublePanel, WrittenPanel } from './panels'
import { rememberSpeed } from './speed'
import { SpeedControl } from './SpeedControl'
import { TrackLine } from './TrackLine'
import styles from './Tracker.module.css'

const NO_BLOCKS: readonly BlockView[] = []

type Tone = 'work' | 'wait' | 'ok' | 'bad'

/** The status icon beside the headline. The words always say the same thing, so status is never colour alone. */
const TONE: Readonly<Record<Headline['is'], Tone>> = {
  not_started: 'work',
  starting: 'work',
  working: 'work',
  found: 'work',
  drafting: 'work',
  waiting: 'wait',
  approved: 'ok',
  written: 'ok',
  nothing_to_write: 'ok',
  declined: 'bad',
  stopped: 'bad',
}

function ToneMark({ tone }: { tone: Tone }) {
  switch (tone) {
    case 'work':
      return <IconSpinner strokeWidth={2.2} />
    case 'wait':
      return <IconPause strokeWidth={2.2} />
    case 'ok':
      return <IconCheck strokeWidth={2.2} />
    case 'bad':
      return <IconX strokeWidth={2.2} />
  }
}

export interface TrackerProps {
  readonly runId: string
  readonly view: LiveView
  /** The blocks of the run's use case. Undefined while it loads: the header and status show, the line waits. */
  readonly blocks: readonly BlockView[] | undefined
  readonly title: string
  /** The overview links its title to the run page. */
  readonly titleTo?: string
}

/** The run view: the use case name, the speed, the headline and subline as one status region, and the line with its one panel. */
export function Tracker({ runId, view, blocks, title, titleTo }: TrackerProps) {
  const reduced = useReducedMotion()
  const titleId = useId()
  const headline = useRef<HTMLHeadingElement>(null)
  const { track, plan } = view.track(blocks ?? NO_BLOCKS)
  const spot = track.panel
  const decision = useDecision(spot?.is === 'approval' ? spot.approvalId : null)
  const canDecide = decision.state?.panel.kind === 'can_decide'
  const tone = TONE[track.headline.is]
  const focusHeadline = useCallback(() => headline.current?.focus(), [])

  function setSpeed(speed: Speed) {
    rememberSpeed(speed)
    view.controls.setSpeed(speed)
  }

  const panel =
    spot?.is === 'approval' ? (
      <ApprovalPanel decision={decision} gate={track.gate} atHead={view.atHead} onLeave={focusHeadline} />
    ) : spot?.is === 'trouble' ? (
      <TroublePanel key={spot.attempt} runId={runId} spot={spot} atHead={view.atHead} onRetried={view.controls.reconnect} onLeave={focusHeadline} />
    ) : spot?.is === 'written' ? (
      <WrittenPanel spot={spot} onLeave={focusHeadline} />
    ) : null

  return (
    <section className={styles['tracker']} aria-labelledby={titleId} data-at-head={String(view.atHead)} data-speed={String(view.speed)}>
      <header className={styles['top']}>
        <div className={styles['title']}>
          <div>
            <h1 id={titleId}>{titleTo ? <Link to={titleTo}>{title}</Link> : title}</h1>
          </div>
          {track.attempt > 1 ? <span className={styles['attempt']}>{attemptWords(track.attempt)}</span> : null}
        </div>
        <SpeedControl value={view.speed} onChange={setSpeed} />
      </header>
      {/* Speaks only at the newest frame, so a replay or a catch-up never reads out old summaries. */}
      <div className={styles['status']} role="status" aria-live={view.atHead ? 'polite' : 'off'} aria-atomic="true">
        <div className={styles['head']}>
          <span className={cx(styles['icon'], styles[tone])} aria-hidden="true">
            <ToneMark tone={tone} />
          </span>
          <h2 ref={headline} tabIndex={-1} className={styles['headline']}>
            {headlineWords(track.headline, { canDecide })}
          </h2>
        </div>
        <p className={styles['subline']}>{track.subline}</p>
      </div>
      {blocks ? (
        <TrackLine track={track} plan={plan} reduced={reduced} panel={panel} />
      ) : (
        <div className={styles['loading']}>
          <Skeleton lines={3} label="Loading the steps." />
        </div>
      )}
    </section>
  )
}
