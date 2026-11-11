import { Link } from 'react-router'
import type { HomeOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { FROM_CHAT } from '../../ui/fromChat'
import { firstSentence, openPathOf, pinnedOf, pinnedWhy, wordsOf } from './home'
import { TONE_ICON } from './HomeItem'
import homeStyles from './Home.module.css'
import styles from './PinnedLine.module.css'

/**
 * During a conversation, the most urgent of the grouped Needs you (spec 3.5): what happened, why, and Open. "N more" is the
 * rest of the same list, so N plus one is the number the rail, the Workflows page and the Planner's answer show.
 */
export function PinnedLine({ home, now }: { home: HomeOut; now: Date }) {
  const pinned = pinnedOf(home)
  if (pinned === null) return null
  const { need, more } = pinned
  const words = wordsOf(need, now)
  const Icon = TONE_ICON[words.tone]
  return (
    <section className={styles['pinned']} aria-label="Most urgent">
      <span className={cx(homeStyles['icon'], homeStyles[words.tone])}>
        <Icon size={20} />
      </span>
      <div className={styles['text']}>
        <b>{words.title}</b>
        <span>{pinnedWhy(need, now)}</span>
      </div>
      <ButtonLink to={openPathOf(need)} state={FROM_CHAT}>
        Open<span className="visually-hidden">: {firstSentence(words.title)}</span>
      </ButtonLink>
      {more > 0 ? (
        <Link to="/workflows" state={FROM_CHAT} className={styles['more']}>
          {more} more<span className="visually-hidden"> that need you</span>
        </Link>
      ) : null}
    </section>
  )
}
