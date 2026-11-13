import { useCallback, useEffect, useReducer, useRef, useState, type RefObject } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { useCapabilities } from '../../api/capabilityQueries'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useApproval, useMe, usePutAddressBack, useRemoveSoftware, useRestoreSoftware, useRun, useStartRun, useUseNewAddress, useWatchlist } from '../../api/queries'
import type { LastCheckView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { IconChevronRight } from '../../ui/icons'
import { ShieldMark } from '../settings/marks'
import { AddSoftware } from './AddSoftware'
import { pressCheckNow } from './checkNow'
import { FindSoftware } from './FindSoftware'
import { askButtonId } from './NewAddress'
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
  UNDO_ID,
  type ChangeFeedback,
  type Moved,
} from './removal'
import { declinedNext, declinedOfSteps, declinedWithNext } from '../run/words'
import { BackToWatchlist, SoftwareItem, softwarePath } from './SoftwareItem'
import {
  addressAttentionOf,
  decisionsOf,
  decisionTitle,
  DECISION_NOTE,
  emptyWords,
  nextCheckOf,
  REFRESH_MS,
  rowsMatching,
  scheduleRuns,
  singaporeTime,
  softwareLine,
  sourcesNote,
  stateOf,
  stoppedWords,
  waitingWords,
  watchAttention,
  watchRank,
  type Decision,
} from './software'
import styles from './Software.module.css'

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

interface RowsProps {
  readonly rows: readonly WatchedSoftwareView[]
  readonly checkedBy: string | null
  readonly now: Date
}

/** One link of 44 px or more for each software: its name, "1.2.14 → 1.2.16 · checked by Software watchlist", and its pill. Urgent first. */
function Rows({ rows, checkedBy, now }: RowsProps) {
  if (rows.length === 0) return null
  const sorted = [...rows].sort((a, b) => watchRank(a) - watchRank(b))
  return (
    <ul className={styles['list']} aria-label="Software on the watchlist">
      {sorted.map((row) => {
        const state = stateOf(row)
        return (
          <li key={row.id} data-status={row.status} data-software-id={row.id}>
            <Link to={softwarePath(row.id)} className={styles['rowLink']}>
              <span className={styles['who']}>
                <b>{row.name}</b>
                <span className={styles['src']}>{softwareLine(row, now, checkedBy)}</span>
              </span>
              <span className={styles['pill']} data-tone={state.tone}>
                {state.words}
              </span>
              <IconChevronRight size={16} />
            </Link>
          </li>
        )
      })}
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

/**
 * The latest check's declined record, read from its run so the rows say it in the run's own words, and what happens next: the tickets
 * are proposed again at the next check, when one is due.
 */
function useLastCheckDeclined(view: WatchlistView | null, nameOf: (id: string) => string): string | null {
  const last = view?.last_check
  const run = useRun(last?.state === 'rejected' ? last.run_id : '')
  if (run.data?.state !== 'rejected') return null
  const declined = declinedOfSteps(run.data.approval.steps)
  if (!declined) return null
  return declinedWithNext(declined, declinedNext({ test: run.data.test, watchlist: true }, nextCheckOf(view), new Date()), nameOf)
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

interface LoadedProps {
  readonly view: WatchlistView | null
  readonly operator: boolean
  readonly answeredAt: number
  readonly now: Date
  /** Set on a software's own page. The Watchlist itself has none. */
  readonly rowId: string | null
}

function Loaded({ view, operator, answeredAt, now, rowId }: LoadedProps) {
  const capabilities = useCapabilities().data?.capabilities
  const sources = sourcesNote(capabilities)
  const [query, setQuery] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const useAddress = useUseNewAddress()
  const putBack = usePutAddressBack()
  const [confirming, setConfirming] = useState<string | null>(null)
  const changes = useLatch()
  const navigate = useNavigate()
  const arrivedWith: unknown = useLocation().state
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
  const declined = useLastCheckDeclined(view, nameOf)
  const checkedBy = scheduled && !paused ? 'Software watchlist' : null

  const landOn = useSearchParams()[0].get('row')
  if (rowId === null && landOn !== null && software.some((row) => row.id === landOn)) return <Navigate to={softwarePath(landOn)} replace state={arrivedWith} />

  const notice = (
    <Notice
      box={noticeBox}
      feedback={feedback}
      scheduled={scheduled}
      paused={paused}
      onUndo={(notice) => (notice.kind === 'switched' ? pressUndoAddress(changes, putBack.mutate, notice, dispatch, words) : notice.kind === 'removed' ? pressUndo(changes, restore.mutate, notice.row, dispatch, words) : undefined)}
      onDismiss={dismiss}
    />
  )

  if (rowId !== null) {
    const row = software.find((item) => item.id === rowId)
    if (!row) {
      return (
        <>
          <BackToWatchlist />
          {notice}
          {feedback.notice?.kind === 'removed' ? null : <p className="muted">That software isn’t on the Watchlist any more.</p>}
        </>
      )
    }
    return (
      <>
        {notice}
        <SoftwareItem
          row={row}
          operator={operator}
          scheduled={scheduled}
          paused={paused}
          historyOpen={historyOpen}
          removing={feedback.busy?.act === 'remove' && feedback.busy.id === row.id}
          confirming={confirming === row.id}
          switching={feedback.busy?.act === 'switch' && feedback.busy.id === row.id}
          nameOf={nameOf}
          capabilities={capabilities}
          declined={declined}
          lastCheckStopped={view?.last_check?.state === 'failed'}
          onToggleHistory={() => setHistoryOpen((open) => !open)}
          onRemove={() => pressRemove(changes, removal.mutate, row, dispatch, words)}
          onAskAddress={() => setConfirming(row.id)}
          onCancelAddress={() => {
            setConfirming(null)
            requestAnimationFrame(() => document.getElementById(askButtonId(row.id))?.focus())
          }}
          onConfirmAddress={() => {
            if (!row.moved_to) return
            const moved: Moved = { id: row.id, name: row.name, ref: row.source.ref, movedTo: row.moved_to }
            pressUseNewAddress(changes, useAddress.mutate, moved, dispatch, words, () => setConfirming(null))
          }}
        />
      </>
    )
  }

  return (
    <>
      {operator && view && !paused && software.length > 0 ? <CheckNow useCaseId={view.use_case_id} /> : null}
      {view?.last_check?.state === 'failed' ? <LastCheckStopped last={view.last_check} /> : null}
      {notice}
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
              <ButtonLink to={softwarePath(item.id)}>
                Open it<span className="visually-hidden">: {item.name}</span>
              </ButtonLink>
            </div>
          ))}
        </section>
      ) : null}
      <section className={styles['section']} aria-label="Software we watch">
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
        <Rows rows={rows} checkedBy={checkedBy} now={now} />
        {operator ? (
          <AddSoftware software={software} onShowRow={(id) => void navigate(softwarePath(id))} onAdded={(name) => dispatch({ type: 'added', name })} />
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

export function SoftwareRoute({ now }: { now: Date }) {
  const me = useMe()
  const watchlist = useWatchlist({ poll: REFRESH_MS })
  const { softwareId = null } = useParams()
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
  return <Loaded view={watchlist.data} operator={me.data.roles.includes('operator')} answeredAt={Math.max(watchlist.dataUpdatedAt, watchlist.errorUpdatedAt)} now={now} rowId={softwareId} />
}
