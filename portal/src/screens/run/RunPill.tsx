import { cx } from '../../ui/cx'
import type { Headline } from './words'
import styles from './RunPage.module.css'

/** The run's one state pill, the same on the card, the panel and the page. */
export function RunPill({ pill }: { pill: Headline['pill'] }) {
  return (
    <span className={cx(styles['pill'], styles[pill.tone])} data-run-pill>
      {pill.label}
    </span>
  )
}
