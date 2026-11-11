import { useCallback, useEffect, useReducer, useRef, useState, type RefObject } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { useCapabilities } from '../../api/capabilityQueries'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useApproval, useMe, usePutAddressBack, useRemoveSoftware, useRestoreSoftware, useRun, useStartRun, useUseNewAddress, useWatchlist } from '../../api/queries'
import type { LastCheckView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { IconExternal } from '../../ui/icons'
import { ShieldMark } from '../settings/marks'
import { TicketKeys, TicketLink } from '../jira/TicketKeys'
import { AddSoftware } from './AddSoftware'
import { pressCheckNow } from './checkNow'
import { FindSoftware } from './FindSoftware'
import { askButtonId, MovedNote, NotFoundNote } from './NewAddress'
import { Schedule } from './Schedule'
import {
  changeFeedback,
  escapeDismisses,
  NO_FEEDBACK,
  NOTICE_ID,
  noticeButtons,
  noticeWords,
  pressRemove,
  pressUndo,
  pressUndoAddress,
  pressUseNewAddress,
  PROBLEM_ID,
  removeButtonId,
  UNDO_ID,
  type ChangeFeedback,
  type Moved,
} from './removal'
import { SoftwareHistory } from './SoftwareHistory'
import {
  addressAttentionOf,
  cantCheckWords,
  decisionsOf,
  decisionTitle,
  DECISION_NOTE,
  emptyWords,
  newestOf,
  oursOf,
  rowDomId,
  rowsMatching,
  scheduleRuns,
  singaporeTime,
  sourcesNote,
  statusTone,
  statusWords,
  stoppedWords,
  ticketsOf,
  waitingWords,
  watchAttention,
  type Decision,
} from './software'
import styles from './Software.module.css'

const REFRESH_MS = 15_000

function useFocusOnceRendered(feedback: ChangeFeedback) {
  const focusedFor = useRef<ChangeFeedback | null>(null)
  useEffect(() => {
    if (feedback.focusTargetId === null || focusedFor.current === feedback) return
    const target = document.getElementById(feedback.focusTargetId)
    if (!target) return
    target.focus()
    focusedFor.current = feedback
  })
}

interface RowProps {
  readonly row: WatchedSoftwareView
  readonly operator: boolean
  readonly scheduled: boolean
  readonly paused: boolean
  readonly open: boolean
  readonly removing: boolean
  readonly confirming: boolean
  readonly switching: boolean
  readonly nameOf: (id: string) => string
  readonly onToggle: () => void
  readonly onRemove: () => void
  readonly onAskAddress: () => void
  readonly onConfirmAddress: () => void
  readonly onCancelAddress: () => void
}

function Row({ row, operator, scheduled, paused, open, removing, confirming, switching, nameOf, onToggle, onRemove, onAskAddress, onConfirmAddress, onCancelAddress }: RowProps) {
  const historyId = `history-${row.id}`
  const newest = newestOf(row)
  const ours = oursOf(row)
  return (
    <li id={rowDomId(row.id)} tabIndex={-1} className={styles['row']} data-status={row.status}>
      <div className={styles['who']}>
        <b>{row.name}</b>
        <span className={styles['src']}>
          GitHub ·{' '}
          <a href={row.source.url} target="_blank" rel="noopener noreferrer">
            {row.source.ref}
            <IconExternal size={12} />
            <span className="visually-hidden"> (opens GitHub in a new tab)</span>
          </a>
        </span>
      </div>
      <dl className={styles['versions']}>
        <div>
          <dt>Ours</dt>
          <dd>
            {ours.version}
            <span className={styles['src']}><TicketKeys text={ours.note} keys={ticketsOf(row)} /></span>
          </dd>
        </div>
        <div>
          <dt>Newest</dt>
          <dd>
            {newest.version}
            {newest.note ? <span className={styles['src']}>{newest.note}</span> : null}
          </dd>
        </div>
      </dl>
      <div className={styles['state']}>
        <span className={styles['pill']} data-tone={statusTone[row.status]}>
          {statusWords(row)}
        </span>
        {row.status === 'cant_check' && !row.not_found ? <span className={styles['src']}>{cantCheckWords(row.problem, { scheduled, paused })}</span> : null}
        <NotFoundNote row={row} operator={operator} scheduled={scheduled} paused={paused} />
        <MovedNote row={row} operator={operator} confirming={confirming} busy={switching} onAsk={onAskAddress} onConfirm={onConfirmAddress} onCancel={onCancelAddress} />
        {row.status === 'ticket_open' && row.open_ticket ? (
          <span className={styles['src']}>
            <TicketLink ticketKey={row.open_ticket} />
          </span>
        ) : null}
      </div>
      <div className={styles['acts']}>
        <Button aria-expanded={open} aria-controls={open ? historyId : undefined} onClick={onToggle}>
          {open ? 'Hide history' : 'History'}
          <span className="visually-hidden"> of {row.name}</span>
        </Button>
        {operator ? (
          <Button id={removeButtonId(row.id)} loading={removing} onClick={onRemove}>
            Remove<span className="visually-hidden"> {row.name}</span>
          </Button>
        ) : null}
      </div>
      {open ? <SoftwareHistory row={row} nameOf={nameOf} id={historyId} /> : null}
    </li>
  )
}

interface RowsProps {
  readonly rows: readonly WatchedSoftwareView[]
  readonly operator: boolean
  readonly scheduled: boolean
  readonly paused: boolean
  readonly opened: string | null
  readonly removing: string | null
  readonly confirming: string | null
  readonly switching: string | null
  readonly nameOf: (id: string) => string
  readonly onToggle: (id: string) => void
  readonly onRemove: (row: WatchedSoftwareView) => void
  readonly onAskAddress: (row: WatchedSoftwareView) => void
  readonly onConfirmAddress: (row: WatchedSoftwareView) => void
  readonly onCancelAddress: (row: WatchedSoftwareView) => void
}

function Rows({ rows, ...rest }: RowsProps) {
  if (rows.length === 0) return null
  return (
    <ul className={styles['list']}>
      {rows.map((row) => (
        <Row
          key={row.id}
          row={row}
          operator={rest.operator}
          scheduled={rest.scheduled}
          paused={rest.paused}
          open={rest.opened === row.id}
          removing={rest.removing === row.id}
          confirming={rest.confirming === row.id}
          switching={rest.switching === row.id}
          nameOf={rest.nameOf}
          onToggle={() => rest.onToggle(row.id)}
          onRemove={() => rest.onRemove(row)}
          onAskAddress={() => rest.onAskAddress(row)}
          onConfirmAddress={() => rest.onConfirmAddress(row)}
          onCancelAddress={() => rest.onCancelAddress(row)}
        />
      ))}
    </ul>
  )
}

function CheckNow({ useCaseId }: { useCaseId: string }) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useNavigate()
  const words = useErrorWords()
  return (
    <div className={styles['checkNow']}>
      <Button loading={start.isPending} onClick={() => pressCheckNow(latch, start.mutate, useCaseId, (runId) => void navigate(`/runs/${runId}`))}>
        Check now
      </Button>
      {start.isError ? (
        <p className={styles['error']} role="alert">
          {words(start.error)}
        </p>
      ) : null}
    </div>
  )
}

function LastCheckStopped({ last }: { last: LastCheckView }) {
  const run = useRun(last.run_id)
  const reason = run.data?.state === 'failed' ? run.data.reason : null
  return (
    <div className={styles['stopped']}>
      <p>
        <b>{stoppedWords(reason)}</b> Started {singaporeTime(last.started_at)}, Singapore time.
      </p>
      <Link to={`/runs/${last.run_id}`}>Open the run</Link>
    </div>
  )
}

function DecisionBar({ decision }: { decision: Decision }) {
  const approval = useApproval(decision.approvalId)
  const tickets = approval.data?.actions.length ?? decision.software
  const cannot = approval.data !== undefined && !approval.data.you_can_decide
  return (
    <div className={styles['decision']}>
      <ShieldMark size={20} />
      <div>
        <b>{decisionTitle(tickets)}</b>
        <span>{DECISION_NOTE}</span>
      </div>
      {cannot ? (
        <span className={styles['waitingFor']}>{waitingWords(approval.data?.why_not ?? null)}</span>
      ) : (
        <ButtonLink to={`/approvals/${decision.approvalId}`} variant="primary">
          Review and decide
        </ButtonLink>
      )}
    </div>
  )
}

interface NoticeProps {
  readonly box: RefObject<HTMLDivElement | null>
  readonly feedback: ChangeFeedback
  readonly scheduled: boolean
  readonly paused: boolean
  readonly onUndo: (notice: NonNullable<ChangeFeedback['notice']>) => void
  readonly onDismiss: () => void
}

/** The status line stays on the page when it is empty, so a screen reader hears each new message. */
function Notice({ box, feedback, scheduled, paused, onUndo, onDismiss }: NoticeProps) {
  const { notice } = feedback
  return (
    <>
      <div ref={box} id={NOTICE_ID} tabIndex={-1} className={styles['notice']}>
        <p role="status">{notice ? noticeWords(notice, { scheduled, paused }) : ''}</p>
        {notice ? (
          <div className={styles['actions']}>
            {noticeButtons(notice).map((label) =>
              label === 'Undo' && (notice.kind === 'removed' || notice.kind === 'switched') ? (
                <Button key={label} id={UNDO_ID} loading={feedback.busy?.act === 'restore' || feedback.busy?.act === 'switchBack'} onClick={() => onUndo(notice)}>
                  Undo
                </Button>
              ) : (
                <Button key={label} onClick={onDismiss}>
                  Dismiss
                </Button>
              ),
            )}
          </div>
        ) : null}
      </div>
      {feedback.problem ? (
        <p className={styles['error']} id={PROBLEM_ID} tabIndex={-1} role="alert">
          {feedback.problem}
        </p>
      ) : null}
    </>
  )
}

function Loaded({ view, operator, answeredAt }: { view: WatchlistView | null; operator: boolean; answeredAt: number }) {
  const sources = sourcesNote(useCapabilities().data?.capabilities)
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const useAddress = useUseNewAddress()
  const putBack = usePutAddressBack()
  const [confirming, setConfirming] = useState<string | null>(null)
  const changes = useLatch()
  const noticeBox = useRef<HTMLDivElement>(null)
  useFocusOnceRendered(feedback)

  const dismiss = useCallback(() => {
    // Only focus inside the notice goes with it. Escape from anywhere else on the page leaves focus where it is.
    if (noticeBox.current?.contains(document.activeElement)) {
      const next = document.getElementById('find-software') ?? document.querySelector<HTMLElement>('main h1')
      next?.focus()
    }
    dispatch({ type: 'dismissed' })
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (escapeDismisses(event, feedback)) dismiss()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [feedback, dismiss])

  const software = view?.software ?? []
  const scheduled = scheduleRuns(view?.schedule)
  const paused = view?.state === 'paused'
  const rows = rowsMatching(software, query)
  const shown = rows.length
  const decisions = decisionsOf(software)
  const addresses = addressAttentionOf(software)
  const searching = query.trim() !== ''

  const rowProps = {
    operator,
    scheduled,
    paused,
    opened,
    removing: feedback.busy?.act === 'remove' ? feedback.busy.id : null,
    confirming,
    switching: feedback.busy?.act === 'switch' ? feedback.busy.id : null,
    nameOf,
    onAskAddress: (row: WatchedSoftwareView) => setConfirming(row.id),
    onCancelAddress: (row: WatchedSoftwareView) => {
      setConfirming(null)
      requestAnimationFrame(() => document.getElementById(askButtonId(row.id))?.focus())
    },
    onConfirmAddress: (row: WatchedSoftwareView) => {
      if (!row.moved_to) return
      const moved: Moved = { id: row.id, name: row.name, ref: row.source.ref, movedTo: row.moved_to }
      pressUseNewAddress(changes, useAddress.mutate, moved, dispatch, words, () => setConfirming(null))
    },
    onToggle: (id: string) => setOpened((current) => (current === id ? null : id)),
    onRemove: (row: WatchedSoftwareView) => pressRemove(changes, removal.mutate, row, dispatch, words),
  }

  const showRow = (id: string) => {
    setQuery('')
    setOpened(null)
    requestAnimationFrame(() => {
      const row = document.getElementById(rowDomId(id))
      row?.focus()
      row?.scrollIntoView?.({ block: 'center' })
    })
  }

  const landOn = useSearchParams()[0].get('row')
  const landOnListed = landOn !== null && software.some((row) => row.id === landOn)
  const landed = useRef(false)
  useEffect(() => {
    if (landed.current || landOn === null || !landOnListed) return
    landed.current = true
    showRow(landOn)
  }, [landOn, landOnListed])

  return (
    <>
      {operator && view && !paused && software.length > 0 ? <CheckNow useCaseId={view.use_case_id} /> : null}
      {view?.last_check?.state === 'failed' ? <LastCheckStopped last={view.last_check} /> : null}
      <Notice
        box={noticeBox}
        feedback={feedback}
        scheduled={scheduled}
        paused={paused}
        onUndo={(notice) => (notice.kind === 'switched' ? pressUndoAddress(changes, putBack.mutate, notice, dispatch, words) : notice.kind === 'removed' ? pressUndo(changes, restore.mutate, notice.row, dispatch, words) : undefined)}
        onDismiss={dismiss}
      />
      {decisions.length > 0 || addresses.length > 0 ? (
        <section className={styles['section']} aria-labelledby="needs-attention-heading">
          <h2 id="needs-attention-heading">
            Needs attention <span className={styles['count']}>{watchAttention(software)}</span>
          </h2>
          {decisions.map((decision) => (
            <DecisionBar key={decision.approvalId} decision={decision} />
          ))}
          {addresses.map((item) => (
            <div key={item.id} className={styles['addressBar']}>
              <div>
                <b>{item.words}</b>
              </div>
              <Button onClick={() => showRow(item.id)}>
                Show it<span className="visually-hidden"> on the list: {item.name}</span>
              </Button>
            </div>
          ))}
        </section>
      ) : null}
      <section className={styles['section']} aria-labelledby="software-we-watch-heading">
        <h2 id="software-we-watch-heading">
          Software we watch <span className={styles['count']}>{shown}</span>
        </h2>
        {software.length > 0 || searching ? <FindSoftware query={query} shown={shown} onChange={setQuery} /> : null}
        {software.length === 0 && !searching ? (
          <div className={styles['empty']}>
            <b>No software yet</b>
            <span>{emptyWords({ operator, scheduled: view === null || scheduleRuns(view.schedule), paused })}</span>
          </div>
        ) : null}
        {searching && shown === 0 ? (
          <div className={styles['empty']}>
            <b>Nothing matches</b>
            <span>Try another name.</span>
            <div>
              <Button onClick={() => setQuery('')}>Clear the search</Button>
            </div>
          </div>
        ) : null}
        <Rows rows={rows} {...rowProps} />
        {operator ? (
          <AddSoftware software={software} onShowRow={showRow} onAdded={(name) => dispatch({ type: 'added', name })} />
        ) : null}
      </section>
      <section className={styles['section']} aria-labelledby="how-checked-heading">
        <h2 id="how-checked-heading">How it’s checked</h2>
        {view ? (
          <Schedule
            schedule={view.schedule}
            operator={operator}
            useCaseId={view.use_case_id}
            paused={paused}
            answeredAt={answeredAt}
            onResumed={() => dispatch({ type: 'resumed' })}
          />
        ) : null}
        {sources ? <p className="muted">{sources}</p> : null}
      </section>
    </>
  )
}

export function SoftwareRoute() {
  const me = useMe()
  const watchlist = useWatchlist({ poll: REFRESH_MS })
  if ((watchlist.isError && !watchlist.data) || me.isError) {
    return (
      <>
        <p>The software list could not be loaded.</p>
        <Button onClick={() => void Promise.all([watchlist.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (watchlist.data === undefined || !me.data) {
    return (
      <p className="muted" role="status">
        Loading the software list
      </p>
    )
  }
  return <Loaded view={watchlist.data} operator={me.data.roles.includes('operator')} answeredAt={Math.max(watchlist.dataUpdatedAt, watchlist.errorUpdatedAt)} />
}
