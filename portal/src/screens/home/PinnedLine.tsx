import { Link } from '../../ui/Link'
import type { HomeOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { OpenButton } from '../../ui/OpenItem'
import { lineOf, openPathOf, panelItemOf, pinnedOf } from './home'
import styles from './PinnedLine.module.css'

/**
 * The needs strip on top of the chat (the sketch's `.strip`): the most urgent of the grouped Needs you in its short form, tinted by
 * it, with Open and "N more". Open shows a stop or a request in the side panel, and anything else on its page. "N more" is the rest
 * of the same list, so N plus one is the number Workflows and the Planner's answer show. With nothing to do it stays, calm.
 */
export function PinnedLine({ home, now }: { home: HomeOut; now: Date }) {
  const pinned = pinnedOf(home)
  if (pinned === null) {
    return (
      <section className={styles['strip']} aria-label="Needs you" data-tone="calm">
        <span className={styles['dot']} aria-hidden="true" />
        <span className={styles['text']}>Nothing needs you</span>
      </section>
    )
  }
  const { need, more } = pinned
  const { tone, subject, short } = lineOf(need, now)
  const item = panelItemOf(need)
  const open = (
    <>
      Open<span className="visually-hidden">: {`${subject} ${short}`}</span>
    </>
  )
  return (
    <section className={styles['strip']} aria-label="Needs you" data-tone={tone}>
      <span className={styles['dot']} aria-hidden="true" />
      <span className={styles['text']}>
        <b>{subject}</b> {short}
      </span>
      {more > 0 ? (
        <Link to="/workflows" className={styles['more']}>
          {more} more<span className="visually-hidden"> that need you</span>
        </Link>
      ) : null}
      {item ? (
        <OpenButton item={item} to={openPathOf(need)}>
          {open}
        </OpenButton>
      ) : (
        <ButtonLink to={openPathOf(need)}>{open}</ButtonLink>
      )}
    </section>
  )
}
