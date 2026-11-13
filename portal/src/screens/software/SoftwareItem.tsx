import { Link } from 'react-router'
import type { WatchedSoftwareView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconChevronLeft, IconExternal } from '../../ui/icons'
import { AskTheTeam } from '../home/AskTheTeam'
import { TicketKeys } from '../jira/TicketKeys'
import { MovedNote, NotFoundNote } from './NewAddress'
import { removeButtonId } from './removal'
import { SoftwareHistory } from './SoftwareHistory'
import { askWhereWords, cantCheckWords, newestOf, oursOf, rowDomId, sentenceFor, singaporeTime, stateOf, ticketFact, ticketsOf, NOT_AUTOMATIC, WATCHLIST_PATH } from './software'
import workflowStyles from '../workflows/Workflows.module.css'
import styles from './Software.module.css'

export function BackToWatchlist() {
  return (
    <Link to={WATCHLIST_PATH} className={workflowStyles['back']}>
      <IconChevronLeft size={16} />
      Watchlist
    </Link>
  )
}

interface ItemProps {
  readonly row: WatchedSoftwareView
  readonly operator: boolean
  readonly scheduled: boolean
  readonly paused: boolean
  readonly historyOpen: boolean
  readonly removing: boolean
  readonly confirming: boolean
  readonly switching: boolean
  readonly nameOf: (id: string) => string
  /** The workflow that checks the watchlist on its own, or null while it is paused or has no schedule. */
  readonly checkedBy: string | null
  /** The latest check's declined record and what happens next, when an Approver declined it and this software has a newer version. */
  readonly declined: string | null
  readonly lastCheckStopped: boolean
  readonly onToggleHistory: () => void
  readonly onRemove: () => void
  readonly onAskAddress: () => void
  readonly onConfirmAddress: () => void
  readonly onCancelAddress: () => void
}

/**
 * One watched software, as the sketch's software page draws it: the kind line, its name and pill, a banner when GitHub can't find it, then
 * You run, Newest, Upgrade ticket, Checked by and Source. Software GitHub can't find offers Ask the team, as in the sketch. History and
 * Remove stay, because the platform can do both. Remove comes last.
 */
export function SoftwareItem(props: ItemProps) {
  const { row, operator, scheduled, paused, historyOpen, removing, confirming, switching, nameOf, checkedBy, declined, lastCheckStopped } = props
  const state = stateOf(row)
  const ours = oursOf(row)
  const newest = newestOf(row)
  const historyId = `history-${row.id}`
  const checked = row.checked_at ? `last checked ${singaporeTime(row.checked_at)}${lastCheckStopped ? ', didn’t finish' : ''}` : 'Not checked yet'
  return (
    <div id={rowDomId(row.id)} tabIndex={-1} className={styles['item']} data-status={row.status}>
      <BackToWatchlist />
      <div className={workflowStyles['head']}>
        <div>
          <p className={workflowStyles['kind']}>Watchlist</p>
          <h1 tabIndex={-1}>{row.name}</h1>
        </div>
        <span className={styles['pill']} data-tone={state.tone}>
          {state.words}
        </span>
      </div>
      {row.not_found || row.moved_to ? null : <p className={workflowStyles['sentence']}>{sentenceFor(row)}</p>}
      {row.not_found || row.moved_to || (row.status === 'cant_check' && !row.not_found) || declined ? (
        <div className={styles['banner']} data-tone={row.status === 'cant_check' ? 'bad' : 'wait'}>
          {row.status === 'cant_check' && !row.not_found ? <p>{cantCheckWords(row.problem, { scheduled, paused })}</p> : null}
          <NotFoundNote row={row} operator={operator} scheduled={scheduled} paused={paused} />
          <MovedNote row={row} operator={operator} confirming={confirming} busy={switching} onAsk={props.onAskAddress} onConfirm={props.onConfirmAddress} onCancel={props.onCancelAddress} />
          {declined && row.status === 'behind' ? <p>{declined}</p> : null}
        </div>
      ) : null}
      <dl className={styles['facts']}>
        <div>
          <dt>You run</dt>
          <dd>
            {ours.version}
            <span className={styles['src']}>
              <TicketKeys text={ours.note} keys={ticketsOf(row)} />
            </span>
          </dd>
        </div>
        <div>
          <dt>Newest</dt>
          <dd>
            {newest.version}
            {newest.note ? <span className={styles['src']}>{newest.note}</span> : null}
          </dd>
        </div>
        <div>
          <dt>Upgrade ticket</dt>
          <dd>
            <TicketKeys text={ticketFact(row, row.status === 'behind' ? declined : null)} keys={ticketsOf(row)} />
          </dd>
        </div>
        <div>
          <dt>Checked by</dt>
          <dd>
            {checkedBy ? (
              <Link to={WATCHLIST_PATH} className={styles['checker']}>
                {checkedBy}
              </Link>
            ) : (
              NOT_AUTOMATIC
            )}
            <span className={styles['src']}>{checked}</span>
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            <a href={row.source.url} target="_blank" rel="noopener noreferrer" className={styles['source']}>
              {`github.com/${row.source.ref}`}
              <IconExternal size={12} />
              <span className="visually-hidden"> (opens GitHub in a new tab)</span>
            </a>
          </dd>
        </div>
      </dl>
      <div className={styles['acts']}>
        {row.not_found ? <AskTheTeam capability={`Where ${row.name} moved`} starter={askWhereWords(row)} /> : null}
        <Button aria-expanded={historyOpen} aria-controls={historyOpen ? historyId : undefined} onClick={props.onToggleHistory}>
          {historyOpen ? 'Hide history' : 'History'}
          <span className="visually-hidden"> of {row.name}</span>
        </Button>
        {operator ? (
          <Button id={removeButtonId(row.id)} variant="danger-outline" loading={removing} onClick={props.onRemove}>
            Remove from watchlist<span className="visually-hidden"> {row.name}</span>
          </Button>
        ) : null}
      </div>
      {historyOpen ? <SoftwareHistory row={row} nameOf={nameOf} declined={declined} id={historyId} /> : null}
    </div>
  )
}
