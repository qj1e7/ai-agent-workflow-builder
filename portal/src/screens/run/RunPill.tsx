import { cx } from '../../ui/cx'
import { runPill, type StageFacts } from './words'
import styles from './RunPage.module.css'

/** The run's one state pill, the same on the card, the panel and the page, and the same words as a list's row. */
export function RunPill({ facts }: { facts: StageFacts }) {
  const { label, tone } = runPill(facts)
  return (
    <span className={cx(styles['pill'], styles[tone])} data-run-pill>
      {label}
    </span>
  )
}
