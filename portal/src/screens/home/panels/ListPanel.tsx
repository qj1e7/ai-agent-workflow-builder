import { useMemo } from 'react'
import { useMe, useUseCases, useWatchlist } from '../../../api/queries'
import { Button } from '../../../ui/Button'
import { count } from '../../run/words'
import { countLine, REFRESH_MS as WATCH_REFRESH } from '../../software/software'
import { REFRESH_MS, rowsOf, viewerOf } from '../../workflows/workflow'
import { SoftwareRows, WorkflowRows } from './ListRows'
import styles from './Lists.module.css'

const NOTHING: ReadonlySet<string> = new Set()

function Loading({ failed, what, retry }: { failed: boolean; what: string; retry: () => void }) {
  return failed ? (
    <p role="alert">
      I couldn’t read {what} just now. <Button onClick={retry}>Try again</Button>
    </p>
  ) : (
    <p className="muted" role="status">
      Checking {what}
    </p>
  )
}

/** Every workflow the Workflows page lists, with its state, as rows that open the workflow in the panel. */
export function WorkflowsPanel({ now }: { now: Date }) {
  const me = useMe()
  const useCases = useUseCases({ poll: REFRESH_MS })
  const rows = useMemo(() => (me.data && useCases.data ? rowsOf(useCases.data, viewerOf(me.data), 'all', '', NOTHING).map((row) => row.useCase) : null), [me.data, useCases.data])
  if (!rows) return <Loading failed={useCases.isError} what="your workflows" retry={() => void useCases.refetch()} />
  if (rows.length === 0) return <p className={styles['calm']}>There are no workflows yet.</p>
  return (
    <div className={styles['stack']}>
      <p className={styles['count']}>{count(rows.length, 'workflow')}</p>
      <WorkflowRows useCases={rows} label="Workflows" now={now} />
    </div>
  )
}

/** Every software on the watchlist, as the Software page lists it, under the page's own count line. */
export function WatchlistPanel({ now }: { now: Date }) {
  const watchlist = useWatchlist({ poll: WATCH_REFRESH })
  const view = watchlist.data
  if (!view) return <Loading failed={watchlist.isError} what="the watchlist" retry={() => void watchlist.refetch()} />
  const rows = view.software
  if (rows.length === 0) return <p className={styles['calm']}>Nothing is on the Software watchlist yet.</p>
  return (
    <div className={styles['stack']}>
      <p className={styles['count']}>{countLine(rows) ?? count(rows.length, 'software')}</p>
      <SoftwareRows rows={rows} view={view} label="Watchlist" now={now} />
    </div>
  )
}
