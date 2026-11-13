import { useEffect, useState, type CSSProperties } from 'react'
import { AgentFace } from '../../ui/AgentFace'
import { cx } from '../../ui/cx'
import { IconCheck, IconClock, IconGate, IconPlay, IconSearch, IconTicket, IconX, type Icon } from '../../ui/icons'
import { usePauseUnseen } from '../../ui/loops'
import { motionAllowed } from '../../ui/motion'
import { TicketLink } from '../jira/TicketKeys'
import type { Station, StationState, StepIcon, Under } from './runModel'
import { workingWords, type Settled } from './words'
import styles from './RunLine.module.css'

/** The state in words, for a screen reader: the line shows it by shape and colour. */
const STATE_WORDS: Readonly<Record<StationState, string>> = {
  todo: 'Not reached yet: ',
  now: 'Now: ',
  wait: 'Waiting for a yes: ',
  done: 'Done: ',
  err: 'Stopped here: ',
  no: 'Declined: ',
  skip: 'Skipped: ',
}

/** A link takes the state of the step it leads into. */
type Link = 'solid' | 'flow' | 'wait' | 'stop' | 'dead' | 'todo'

const LINK_INTO: Readonly<Record<StationState, Link>> = {
  todo: 'todo',
  now: 'flow',
  wait: 'wait',
  done: 'solid',
  err: 'stop',
  no: 'solid',
  skip: 'dead',
}

const MARCHES: ReadonlySet<Link> = new Set(['flow', 'wait'])

const ICON: Readonly<Record<StepIcon, Icon>> = { schedule: IconClock, person: IconPlay, read: IconSearch, gate: IconGate, write: IconTicket }

/** A stopped run's line first shows the work flowing into the stop for this long, then the stop. */
const REPLAY_MS = 1000
const TICK_MS = 250

function Working({ since, small }: { since: number; small: boolean }) {
  const [words, setWords] = useState(() => workingWords(since, Date.now(), small))
  useEffect(() => {
    const timer = setInterval(() => setWords(workingWords(since, Date.now(), small)), TICK_MS)
    return () => clearInterval(timer)
  }, [since, small])
  return <span className={styles['timer']}>{words}</span>
}

function UnderStep({ under, small }: { under: Under; small: boolean }) {
  switch (under.kind) {
    case 'timer':
      return <Working since={under.since} small={small} />
    case 'tickets':
      return under.written.map((written, index) => (
        <span key={index} className={styles['chip']} title={written.ref}>
          {written.connector === 'jira' ? <TicketLink ticketKey={written.ref} href={written.url} /> : written.ref}
        </span>
      ))
    case 'note':
      return <span>{under.text}</span>
  }
}

function Face({ station }: { station: Station }) {
  if (station.spot.at !== 'agent') return null
  return station.agent ? <AgentFace id={station.agent.id} display={station.agent.display} size={34} state={station.face} /> : <span className={styles['nobody']} />
}

interface RunLineProps {
  readonly stations: readonly Station[]
  /** The step the run reached while the page watched. It lands, and the solid links into it and the step before it grow. */
  readonly arrivedLive: string | null
  /** How the run ended, said under the line once it has. */
  readonly settled: Settled | null
  /** Cards and the side panel: smaller, and without the agents' faces. */
  readonly small?: boolean
}

/** How a run ended, as the one line the page, the panel and the card keep for it. */
export function SettledLine({ settled }: { settled: Settled }) {
  return (
    <p className={styles['settled']} data-tone={settled.tone}>
      {settled.tone === 'ok' ? <IconCheck /> : null}
      {settled.text}
    </p>
  )
}

export function RunLine({ stations, arrivedLive, settled, small = false }: RunLineProps) {
  const pauseUnseen = usePauseUnseen()
  const moving = motionAllowed()
  const [replaying, setReplaying] = useState(() => moving && stations.some((station) => station.state === 'err'))
  useEffect(() => {
    if (!replaying) return
    const timer = setTimeout(() => setReplaying(false), REPLAY_MS)
    return () => clearTimeout(timer)
  }, [replaying])
  const arrived = stations.findIndex((station) => station.key === arrivedLive)
  return (
    <div className={cx(styles['line'], small ? styles['small'] : styles['large'])}>
      {/* The steps scroll sideways when the line is too long for its space, so the keyboard can reach them (axe: scrollable-region-focusable). */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className={styles['scroll']} tabIndex={0} role="group" aria-label="Steps">
        <ol className={styles['track']} style={{ '--n': stations.length } as CSSProperties} aria-label="Steps of this run" ref={pauseUnseen}>
          {stations.map((station, index) => {
            const next = stations[index + 1]
            const link = next ? LINK_INTO[next.state] : null
            const grows = link === 'solid' && arrived >= 0 && (index === arrived - 1 || index === arrived - 2)
            const { state } = station
            const StepPicture = ICON[station.icon]
            return (
              <li
                key={station.key}
                className={cx(styles['step'], styles[state], station.spot.at === 'gate' && styles['gate'], index === arrived && styles['arrive'])}
                aria-current={state === 'now' || state === 'wait' ? 'step' : undefined}
                data-state={state}
                data-replay={(replaying && state === 'err') || undefined}
              >
                {link ? (
                  <span
                    className={cx(styles['link'], grows && styles['grow'])}
                    data-link={link}
                    data-march={(moving && MARCHES.has(link)) || undefined}
                    data-replay={(replaying && next?.state === 'err') || undefined}
                    aria-hidden="true"
                  />
                ) : null}
                {small ? null : (
                  <span className={styles['who']}>
                    <Face station={station} />
                  </span>
                )}
                <span className={styles['dot']}>
                  <StepPicture />
                  <span className={styles['tick']} data-shown={state === 'done' || undefined}>
                    <IconCheck />
                  </span>
                  <span className={styles['stopMark']} data-shown={state === 'err' || undefined}>
                    <IconX />
                  </span>
                </span>
                <span className={styles['label']}>
                  <span className="visually-hidden">{STATE_WORDS[state]}</span>
                  {station.label}
                </span>
                {station.under ? (
                  <span className={styles['under']}>
                    <UnderStep under={station.under} small={small} />
                  </span>
                ) : null}
              </li>
            )
          })}
        </ol>
      </div>
      {settled ? <SettledLine settled={settled} /> : null}
    </div>
  )
}
