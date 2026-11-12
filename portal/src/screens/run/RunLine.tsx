import type { CSSProperties, ReactNode } from 'react'
import { Mark } from '../../shell/icons'
import { AgentFace } from '../../ui/AgentFace'
import { cx } from '../../ui/cx'
import { IconCheck, IconLock, IconShield, IconX } from '../../ui/icons'
import { usePauseUnseen } from '../../ui/loops'
import { motionAllowed } from '../../ui/motion'
import { PersonInitial } from '../../ui/PersonInitial'
import type { Station, StationState } from './runModel'
import type { NameOf } from './words'
import styles from './RunLine.module.css'

const STATE_PREFIX: Partial<Record<StationState, string>> = { done: 'Done: ', now: 'Now: ', todo: 'Not reached yet: ' }

/** A link takes the state of the step it leads into (spec 10.1). */
type Link = 'solid' | 'flow' | 'wait' | 'stop' | 'dead' | 'todo'

const LINK_INTO: Readonly<Record<StationState, Link>> = {
  done: 'solid',
  declined: 'solid',
  now: 'flow',
  wait: 'wait',
  fail: 'stop',
  skip: 'dead',
  todo: 'todo',
}

const MARCHES: ReadonlySet<Link> = new Set(['flow', 'wait'])

function subOf(station: Station, startedAt: string): string | null {
  switch (station.state) {
    case 'skip':
      return station.sub ?? 'Not needed'
    case 'fail':
      return 'Stopped here'
    case 'wait':
      return 'Waiting for a yes'
    case 'declined':
      return 'Declined'
    default:
      if (station.spot.at === 'gate' && station.state === 'done') return 'Approved'
      if (station.spot.at === 'started') return startedAt || null
      return station.sub
  }
}

function dotOf(station: Station, small: boolean): ReactNode {
  const gate = small ? 12 : 18
  const mark = small ? 11 : 14
  if (station.spot.at === 'gate') {
    if (station.state === 'wait') return <IconLock size={gate} />
    if (station.state === 'declined') return <IconX size={small ? 11 : 16} />
    return <IconShield size={gate} />
  }
  if (station.ended) return <span className={styles['endDot']} />
  if (station.state === 'done') return <IconCheck size={mark} />
  if (station.state === 'fail') return <IconX size={mark} />
  return null
}

function Who({ station, nameOf }: { station: Station; nameOf: NameOf }) {
  const { who } = station
  switch (who.kind) {
    case 'person':
      return <PersonInitial name={nameOf(who.id)} size={44} />
    case 'agent':
      return who.agent ? <AgentFace id={who.agent.id} display={who.agent.display} size={56} state={station.face} /> : <span className={styles['nobody']} />
    case 'platform':
      return (
        <span className={styles['app']}>
          <Mark height={18} />
        </span>
      )
    case 'none':
      return null
  }
}

interface RunLineProps {
  readonly stations: readonly Station[]
  /** The step the run reached while the page watched. It lands, and the solid links into it and the step before it grow. */
  readonly arrivedLive: string | null
  readonly startedAt: string
  readonly nameOf: NameOf
  /** The side panel's line: upright, smaller, and without the agents' faces. */
  readonly small?: boolean
}

export function RunLine({ stations, arrivedLive, startedAt, nameOf, small = false }: RunLineProps) {
  const pauseUnseen = usePauseUnseen()
  const moving = motionAllowed()
  const arrived = stations.findIndex((station) => station.key === arrivedLive)
  const line = (
    <ol className={cx(styles['line'], small && styles['small'])} style={{ '--n': stations.length } as CSSProperties} aria-label="Steps of this run" ref={pauseUnseen}>
      {stations.map((station, index) => {
        const next = stations[index + 1]
        const link = next ? LINK_INTO[next.state] : null
        const grows = link === 'solid' && arrived >= 0 && (index === arrived - 1 || index === arrived - 2)
        const sub = subOf(station, startedAt)
        const said = STATE_PREFIX[station.state]
        const current = station.state === 'now' || station.state === 'wait'
        return (
          <li
            key={station.key}
            className={cx(styles['station'], styles[station.state], station.spot.at === 'gate' && styles['gate'], index === arrived && styles['arrive'])}
            aria-current={current ? 'step' : undefined}
            data-state={station.state}
          >
            {link ? (
              <span
                className={cx(styles['link'], grows && styles['grow'])}
                data-link={link}
                data-march={(moving && MARCHES.has(link)) || undefined}
                aria-hidden="true"
              />
            ) : null}
            {small ? null : (
              <div className={styles['who']}>
                <Who station={station} nameOf={nameOf} />
              </div>
            )}
            <div className={styles['dotWrap']}>
              <span className={styles['dot']}>{dotOf(station, small)}</span>
            </div>
            <div className={styles['label']}>
              {said ? <span className="visually-hidden">{said}</span> : null}
              {station.label}
              {sub ? <small>{sub}</small> : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
  return small ? line : <div className={styles['stage']}>{line}</div>
}
