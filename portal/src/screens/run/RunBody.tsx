import type { ReactNode } from 'react'
import { cx } from '../../ui/cx'
import styles from './RunPage.module.css'

interface RunBodyProps {
  readonly view: 'main' | 'n8n'
  readonly stage: ReactNode
  /** What sits right under the stage, in its column: the AI troubleshooter's card on a stop. Null otherwise. */
  readonly below: ReactNode
  /** The decision and the history, beside the stage from 1240 px and under it before. */
  readonly side: ReactNode
}

/**
 * The run page's body. Its shape never depends on the run's state: the stage column is always the same width, so a live stop or retry
 * moves only what changed and never slides the steps (the sketch's motion rule). The card under the stage lives in the stage's column.
 */
export function RunBody({ view, stage, below, side }: RunBodyProps) {
  return (
    <div className={cx(styles['body'], view !== 'n8n' && styles['withStage'])}>
      {view === 'n8n' ? null : (
        <div className={styles['stageCol']}>
          {stage}
          {below}
        </div>
      )}
      <div className={styles['side']}>{side}</div>
    </div>
  )
}
