import { Link, useLocation, useMatch } from 'react-router'
import { HOME_REFRESH_MS, useHome } from '../api/homeQueries'
import { useApproval, useRun, useUseCase, useWatchlist } from '../api/queries'
import { needsTotal } from '../screens/home/home'
import { watchAttention } from '../screens/software/software'
import { cx } from '../ui/cx'
import { PAGES, railCountFor, railCurrent, RAIL_PAGE_IDS, type PageId } from './routes'
import styles from './Rail.module.css'

interface RailProps {
  readonly operator: boolean
  readonly onList: boolean
}

/** A run page, or an approval page, belongs to Workflows, or to the Watchlist when the run is the watchlist's. */
function useRunsRailItem(): PageId {
  const approval = useMatch('/approvals/:approvalId')
  const run = useMatch('/runs/:runId')
  const approvalView = useApproval(approval?.params.approvalId ?? '', { enabled: approval !== null })
  const runView = useRun(run?.params.runId ?? approvalView.data?.run_id ?? '')
  const useCase = useUseCase(runView.data?.use_case_id ?? '')
  return useCase.data?.template === 'software_watchlist' ? 'software' : 'workflows'
}

/**
 * Chat, Workflows and Watchlist: a column on the left, and a bar across the top at 900 px and narrower. The counts come from
 * the queries Home and the Software page read, so each agrees with the page it leads to.
 */
export function Rail({ operator, onList }: RailProps) {
  const home = useHome({ enabled: onList })
  const watchlist = useWatchlist({ enabled: onList && operator, poll: HOME_REFRESH_MS })
  const { pathname } = useLocation()
  const current = railCurrent(pathname, useRunsRailItem())
  const needs = home.data ? needsTotal(home.data) : 0
  const watch = watchAttention(watchlist.data?.software ?? [])
  return (
    <nav className={styles['rail']} aria-label="Main">
      {RAIL_PAGE_IDS.map((id) => {
        const { path, railLabel, icon: Icon } = PAGES[id]
        const count = railCountFor(id, operator, needs, watch)
        return (
          <Link key={id} to={path} aria-current={current === id ? 'page' : undefined} className={cx(styles['link'])} aria-label={count ? `${railLabel}, ${count.total} ${count.says}` : undefined}>
            <Icon size={22} />
            <span>{railLabel}</span>
            {count ? (
              <span className={styles['count']} aria-hidden="true">
                {count.total}
              </span>
            ) : null}
          </Link>
        )
      })}
    </nav>
  )
}
