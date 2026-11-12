import { isOperator } from '../../api/me'
import { useCapabilities } from '../../api/plannerQueries'
import { useMe, useWatchlist } from '../../api/queries'
import { Button } from '../../ui/Button'
import { checkedByWords, newestOf, nextCheckWords, noScheduleWords, oursOf, REFRESH_MS, scheduleWords, statusTone, statusWords } from './software'
import workflowStyles from '../workflows/Workflows.module.css'
import styles from './Software.module.css'

/**
 * A watched software in the side panel (spec 3.3): its status, the version you run, the newest, what checks it and when.
 * Where and when are said in the Software page's own words, so the panel never claims more than the page. More details opens
 * its row there.
 */
export function SoftwarePanel({ id }: { id: string }) {
  const watchlist = useWatchlist({ poll: REFRESH_MS })
  const capabilities = useCapabilities()
  const me = useMe()
  const view = watchlist.data
  const row = view?.software.find((software) => software.id === id)
  if (watchlist.isError && !view) {
    return (
      <p role="alert">
        The software list could not be loaded. <Button onClick={() => void watchlist.refetch()}>Try again</Button>
      </p>
    )
  }
  if (view === undefined) {
    return (
      <p className="muted" role="status">
        Loading the software list
      </p>
    )
  }
  if (!view || !row) return <p className="muted">That software isn’t on the Software watchlist any more.</p>
  const paused = view.state === 'paused'
  const checkedBy = checkedByWords(capabilities.data?.capabilities)
  return (
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
        {checkedBy ? (
          <div>
            <dt>Checked by</dt>
            <dd>{checkedBy}</dd>
          </div>
        ) : null}
        <div>
          <dt>When</dt>
          <dd>{view.schedule ? `${scheduleWords(view.schedule)} ${nextCheckWords(view.schedule, paused)}` : noScheduleWords({ operator: isOperator(me.data), paused })}</dd>
        </div>
      </dl>
    </>
  )
}
