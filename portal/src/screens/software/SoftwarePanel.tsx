import { isOperator } from '../../api/me'
import { useMe, useWatchlist } from '../../api/queries'
import { Button } from '../../ui/Button'
import { Link } from '../../ui/Link'
import { CHECKER, checksOnItsOwn, nextCheckWords, NOT_AUTOMATIC, noScheduleWords, REFRESH_MS, scheduleWords, sentenceFor, stateOf, WATCHLIST_PATH } from './software'
import workflowStyles from '../workflows/Workflows.module.css'
import styles from './Software.module.css'

/**
 * A watched software in the side panel (spec 3.3): its status, the version you run, the newest, the workflow that checks it and when.
 * Each is said in the Software page's own words, so the panel never claims more than the page. More details opens its page.
 */
export function SoftwarePanel({ id }: { id: string }) {
  const watchlist = useWatchlist({ poll: REFRESH_MS })
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
  const state = stateOf(row)
  return (
    <>
      <div>
        <span className={styles['pill']} data-tone={state.tone}>
          {state.words}
        </span>
      </div>
      <p>{sentenceFor(row)}</p>
      <dl className={workflowStyles['factrows']}>
        <div>
          <dt>Checked by</dt>
          <dd>{checksOnItsOwn(view) ? <Link to={WATCHLIST_PATH}>{CHECKER}</Link> : NOT_AUTOMATIC}</dd>
        </div>
        <div>
          <dt>When</dt>
          <dd>{view.schedule ? `${scheduleWords(view.schedule)} ${nextCheckWords(view.schedule, paused)}` : noScheduleWords({ operator: isOperator(me.data), paused })}</dd>
        </div>
      </dl>
    </>
  )
}
