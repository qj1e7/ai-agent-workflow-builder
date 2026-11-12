import { useWatchlist } from '../../api/queries'
import { Button } from '../../ui/Button'
import type { PanelViewProps } from '../../ui/sidePanel'
import { checkedByWords, newestOf, oursOf, statusTone, statusWords } from './software'
import workflowStyles from '../workflows/Workflows.module.css'
import styles from './Software.module.css'

const SOFTWARE = 'Software'
const REFRESH_MS = 15_000

/** A watched software in the side panel (spec 3.3): its status, the version you run, the newest, and what checks it. More details opens its row on the Software watchlist. */
export function SoftwarePanel({ id, children }: PanelViewProps) {
  const watchlist = useWatchlist({ poll: REFRESH_MS })
  if (watchlist.isError && !watchlist.data) {
    const body = (
      <p role="alert">
        The software list could not be loaded. <Button onClick={() => void watchlist.refetch()}>Try again</Button>
      </p>
    )
    return children({ title: SOFTWARE, page: null, body })
  }
  if (watchlist.data === undefined) {
    const body = (
      <p className="muted" role="status">
        Loading the software list
      </p>
    )
    return children({ title: SOFTWARE, page: null, body })
  }
  const row = watchlist.data?.software.find((software) => software.id === id)
  if (!watchlist.data || !row) return children({ title: SOFTWARE, page: null, body: <p className="muted">That software isn’t on the Software watchlist any more.</p> })
  return children({
    title: row.name,
    page: `/software?row=${encodeURIComponent(row.id)}`,
    body: (
      <>
        <div>
          <span className={styles['pill']} data-tone={statusTone[row.status]}>
            {statusWords(row)}
          </span>
        </div>
        <dl className={workflowStyles['factrows']}>
          <div>
            <dt>You run</dt>
            <dd>{oursOf(row).version}</dd>
          </div>
          <div>
            <dt>Newest</dt>
            <dd>{newestOf(row).version}</dd>
          </div>
          <div>
            <dt>Checked by</dt>
            <dd>{checkedByWords(watchlist.data)}</dd>
          </div>
        </dl>
      </>
    ),
  })
}
