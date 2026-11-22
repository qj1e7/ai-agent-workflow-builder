import { cx } from './cx'
import type { Icon } from './icons'
import styles from './SmallStepLine.module.css'

/** Where a run left a step: done, at work now, waiting for a person, stopped there, or not reached. */
export type StepState = 'done' | 'now' | 'wait' | 'stop' | 'unreached'

export interface SmallStep {
  readonly key: string
  readonly icon: Icon
  readonly state: StepState
}

interface SmallStepLineProps {
  readonly steps: readonly SmallStep[]
  /** What the line says as a whole, such as "Last run: Today 8:00: GitHub didn't answer". */
  readonly label: string
  readonly size?: 'regular' | 'small'
}

/** A workflow's steps as circles, coloured by its last run, for a board tile, a table row and the workflow diagram's key. */
export function SmallStepLine({ steps, label, size = 'regular' }: SmallStepLineProps) {
  return (
    <span className={cx(styles['line'], size === 'small' && styles['small'])} role="img" aria-label={label}>
      {steps.map(({ key, icon: StepIcon, state }) => (
        <span key={key} className={styles['step']} data-state={state}>
          <StepIcon size={size === 'small' ? 11 : 13} />
        </span>
      ))}
    </span>
  )
}
