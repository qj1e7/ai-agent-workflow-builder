import { cx } from '../../ui/cx'
import { statusOf } from './happened'
import { runPill, type NameOf, type StageFacts } from './words'
import styles from './RunPage.module.css'

/**
 * The run's one state pill, the same on the card, the panel and the page, and the same words as a list's row. Where a place can
 * name people (the page and the panel), a run that is writing after an approval says who approved it.
 */
export function RunPill({ facts, nameOf }: { facts: StageFacts; nameOf?: NameOf }) {
  const { label, tone } = nameOf ? statusOf(facts, nameOf) : runPill(facts)
  return (
    <span className={cx(styles['pill'], styles[tone])} data-run-pill>
      {label}
    </span>
  )
}
