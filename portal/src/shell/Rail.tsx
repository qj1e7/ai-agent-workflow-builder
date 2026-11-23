import { Link, useLocation } from 'react-router'
import { useHome } from '../api/homeQueries'
import { cx } from '../ui/cx'
import { PAGES, railCountFor, railCurrent, RAIL_PAGE_IDS } from './routes'
import styles from './Rail.module.css'

interface RailProps {
  readonly onList: boolean
}

/**
 * Chat and Workflows: a column on the left, and a bar across the top at 900 px and narrower. The total comes from
 * the query Home reads, so it agrees with the page it leads to.
 */
export function Rail({ onList }: RailProps) {
  const home = useHome({ enabled: onList })
  const { pathname } = useLocation()
  const current = railCurrent(pathname)
  return (
    <nav className={styles['rail']} aria-label="Browse">
      {RAIL_PAGE_IDS.map((id) => {
        const { path, railLabel, icon: Icon } = PAGES[id]
        const count = railCountFor(id, home.data?.workflows)
        return (
          <Link key={id} to={path} aria-current={current === id ? 'page' : undefined} className={cx(styles['link'])} aria-label={count ? `${railLabel}, ${String(count)} in all` : undefined}>
            <Icon size={20} />
            <span>{railLabel}</span>
            {count ? (
              <span className={styles['count']} aria-hidden="true">
                {count}
              </span>
            ) : null}
          </Link>
        )
      })}
    </nav>
  )
}
