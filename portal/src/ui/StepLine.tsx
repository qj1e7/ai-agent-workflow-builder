import { cx } from './cx'
import { IconClock, IconGate, IconPlay, IconSearch, IconTicket, type Icon } from './icons'
import { motionAllowed } from './motion'
import styles from './StepLine.module.css'

/** Where one step stands: not reached, at work, waiting at the gate, done, stopped, declined or skipped. */
export type StepState = 'todo' | 'now' | 'wait' | 'done' | 'err' | 'no' | 'skip'

/** The picture in a step's circle: the clock or the person that started the run, an agent reading, the gate, the write. */
export type StepIcon = 'schedule' | 'person' | 'read' | 'gate' | 'write'

export const STEP_ICON: Readonly<Record<StepIcon, Icon>> = { schedule: IconClock, person: IconPlay, read: IconSearch, gate: IconGate, write: IconTicket }

/** The state in words, for a screen reader: a step line shows it by shape and colour. */
export const STEP_STATE_WORDS: Readonly<Record<StepState, string>> = {
  todo: 'Not reached yet: ',
  now: 'Now: ',
  wait: 'Waiting for approval: ',
  done: 'Done: ',
  err: 'Stopped here: ',
  no: 'Declined: ',
  skip: 'Skipped: ',
}

export interface StepDraw {
  readonly key: string
  readonly icon: StepIcon
  readonly state: StepState
}

interface StepLineProps {
  readonly steps: readonly StepDraw[]
  /** What the whole line says, such as "Last run: Stopped at Compare". It is the line's only name. */
  readonly label: string
  /** The sketch's two sizes: 28 px circles on a board tile and the Workflows table, and 22 px circles beside a name in a card. */
  readonly size?: 'md' | 'sm'
}

/**
 * The small step line: a workflow's steps as circles joined by a link, coloured by its last run. A step not reached is dashed. It is one
 * picture with one name, so a screen reader reads the sentence and not the circles. The waiting step's ring pulses only while motion is allowed.
 */
export function StepLine({ steps, label, size = 'md' }: StepLineProps) {
  const ring = motionAllowed()
  return (
    <span className={styles['line']} role="img" aria-label={label} data-size={size === 'sm' ? 'sm' : undefined}>
      {steps.map((step) => {
        const Picture = STEP_ICON[step.icon]
        return (
          <span key={step.key} className={cx(styles['dot'], styles[step.state])} data-state={step.state} data-ring={(ring && step.state === 'wait') || undefined}>
            <Picture />
          </span>
        )
      })}
    </span>
  )
}
