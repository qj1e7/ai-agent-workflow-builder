import type { CSSProperties, ReactNode } from 'react'
import { Mark } from '../../shell/icons'
import { AgentFace } from '../../ui/AgentFace'
import { cx } from '../../ui/cx'
import { IconCheck, IconLock, IconShield, IconX } from '../../ui/icons'
import { usePauseUnseen } from '../../ui/loops'
import { PersonInitial } from '../../ui/PersonInitial'
import type { Station, StationState } from './runModel'
import type { NameOf } from './words'
import styles from './RunLine.module.css'

/** Said before each step's name, so a screen reader hears its state as well as its name. */
const SAID: Partial<Record<StationState, string>> = { done: 'Done: ', now: 'Now: ', todo: 'Not reached yet: ' }

function subOf(station: Station, startedAt: string): string | null {
  switch (station.state) {
    case 'skip':
      return 'Not needed'
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

function dotOf(station: Station): ReactNode {
  if (station.spot.at === 'gate') {
    if (station.state === 'wait') return <IconLock size={18} />
    if (station.state === 'declined') return <IconX size={16} />
    return <IconShield size={18} />
  }
  if (station.state === 'done') return <IconCheck size={14} />
  if (station.state === 'fail') return <IconX size={14} />
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
  readonly reach: number
  /** The step the run reached while the page watched, which lands after the line travels to it. */
  readonly arrived: string | null
  readonly startedAt: string
  readonly nameOf: NameOf
}

export function RunLine({ stations, reach, arrived, startedAt, nameOf }: RunLineProps) {
  const pauseUnseen = usePauseUnseen()
  const line = { '--n': stations.length } as CSSProperties
  const fill = { '--f': reach } as CSSProperties
  return (
    <div className={styles['stage']} ref={pauseUnseen}>
      <ol className={styles['line']} style={line} aria-label="Steps of this run">
        <li className={styles['track']} aria-hidden="true" />
        <li className={styles['fill']} style={fill} aria-hidden="true" />
        {stations.map((station) => {
          const sub = subOf(station, startedAt)
          const said = SAID[station.state]
          const current = station.state === 'now' || station.state === 'wait'
          return (
            <li
              key={station.key}
              className={cx(styles['station'], styles[station.state], station.spot.at === 'gate' && styles['gate'], arrived === station.key && styles['arrive'])}
              aria-current={current ? 'step' : undefined}
              data-state={station.state}
            >
              <div className={styles['who']}>
                <Who station={station} nameOf={nameOf} />
              </div>
              <div className={styles['dotWrap']}>
                <span className={styles['dot']}>{dotOf(station)}</span>
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
    </div>
  )
}
