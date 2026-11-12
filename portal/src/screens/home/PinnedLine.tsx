import { Link } from '../../ui/Link'
import type { HomeOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { OpenButton } from '../../ui/OpenItem'
import { firstSentence, openPathOf, panelItemOf, pinnedOf, pinnedWhy, wordsOf } from './home'
import { TONE_ICON } from './HomeItem'
import homeStyles from './Home.module.css'
import styles from './PinnedLine.module.css'

/**
 * During a conversation, the most urgent of the grouped Needs you (spec 3.5): what happened, why, and Open. Open shows a stop or
 * a request in the side panel, and anything else on its page. "N more" is the rest of the same list, so N plus one is the number
 * the rail, the Workflows page and the Planner's answer show.
 */
export function PinnedLine({ home, now }: { home: HomeOut; now: Date }) {
  const pinned = pinnedOf(home)
  if (pinned === null) return null
  const { need, more } = pinned
  const words = wordsOf(need, now)
  const Icon = TONE_ICON[words.tone]
  const item = panelItemOf(need)
  const open = (
    <>
      Open<span className="visually-hidden">: {firstSentence(words.title)}</span>
    </>
  )
  return (
    <section className={styles['pinned']} aria-label="Most urgent">
      <span className={cx(homeStyles['icon'], homeStyles[words.tone])}>
        <Icon size={20} />
      </span>
      <div className={styles['text']}>
        <b>{words.title}</b>
        <span>{pinnedWhy(need, now)}</span>
      </div>
      {item ? (
        <OpenButton item={item} to={openPathOf(need)}>
          {open}
        </OpenButton>
      ) : (
        <ButtonLink to={openPathOf(need)}>{open}</ButtonLink>
      )}
      {more > 0 ? (
        <Link to="/workflows" className={styles['more']}>
          {more} more<span className="visually-hidden"> that need you</span>
        </Link>
      ) : null}
    </section>
  )
}
