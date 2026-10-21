import { useId } from 'react'
import { Link } from 'react-router'
import type { BlockView, TemplateView } from '../api/types'
import { headlineWords, type Headline, type LiveView } from '../run'
import { cx } from '../ui/cx'
import { Skeleton } from '../ui/Feedback'
import { IconCheck, IconPause, IconSpinner, IconX } from '../ui/icons'
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
  /** The template behind the run's use case. Undefined while it loads: the header and status show, the line waits. */
  readonly template: TemplateView | undefined
  readonly title: string
  /** The overview links its title to the run page. */
  readonly titleTo?: string
}

/** The run view: the use case name, the headline and subline as one status region, and the line. */
export function Tracker({ view, template, title, titleTo }: TrackerProps) {
  const titleId = useId()
  const { track } = view.track(template?.blocks ?? NO_BLOCKS)
  const tone = TONE[track.headline.is]

  return (
    <section className={styles['tracker']} aria-labelledby={titleId} data-at-head={String(view.atHead)} data-speed={String(view.speed)}>
      <header className={styles['top']}>
        <div className={styles['title']}>
          <div>
            <h1 id={titleId}>{titleTo ? <Link to={titleTo}>{title}</Link> : title}</h1>
            {template && template.name !== title ? <p className={styles['template']}>{template.name}</p> : null}
          </div>
          {track.attempt > 1 ? <span className={styles['attempt']}>Attempt {track.attempt}</span> : null}
        </div>
      </header>
      <div className={styles['status']} role="status" aria-atomic="true">
        <div className={styles['head']}>
          <span className={cx(styles['icon'], styles[tone])} aria-hidden="true">
            <ToneMark tone={tone} />
          </span>
          <h2 className={styles['headline']}>{headlineWords(track.headline, { canDecide: false })}</h2>
        </div>
        <p className={styles['subline']}>{track.subline}</p>
      </div>
      {template ? (
        <TrackLine track={track} />
      ) : (
        <div className={styles['loading']}>
          <Skeleton lines={3} label="Loading the steps." />
        </div>
      )}
    </section>
  )
}
