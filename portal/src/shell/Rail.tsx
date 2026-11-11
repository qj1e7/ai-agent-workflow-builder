import { NavLink } from 'react-router'
import { HOME_REFRESH_MS, useHome } from '../api/homeQueries'
import { useWatchlist } from '../api/queries'
import { needsTotal } from '../screens/home/home'
import { watchAttention } from '../screens/software/software'
import { cx } from '../ui/cx'
import { PAGES, railCountFor, RAIL_PAGE_IDS } from './routes'
import styles from './Rail.module.css'

interface RailProps {
  readonly operator: boolean
  readonly onList: boolean
}

/**
 * Chat, Workflows and Watchlist: a column on the left, and a bar across the top at 900 px and narrower. The counts come from
 * the queries Home and the Software page read, so each agrees with the page it leads to.
 */
export function Rail({ operator, onList }: RailProps) {
  const home = useHome({ enabled: onList })
  const watchlist = useWatchlist({ enabled: onList && operator, poll: HOME_REFRESH_MS })
  const needs = home.data ? needsTotal(home.data) : 0
  const watch = watchAttention(watchlist.data?.software ?? [])
  return (
    <nav className={styles['rail']} aria-label="Main">
      {RAIL_PAGE_IDS.map((id) => {
        const { path, railLabel, icon: Icon } = PAGES[id]
        const count = railCountFor(id, operator, needs, watch)
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['link'])} aria-label={count ? `${railLabel}, ${count.total} ${count.says}` : undefined}>
            <Icon size={22} />
            <span>{railLabel}</span>
            {count ? (
              <span className={styles['count']} aria-hidden="true">
                {count.total}
              </span>
            ) : null}
          </NavLink>
        )
      })}
    </nav>
  )
}
