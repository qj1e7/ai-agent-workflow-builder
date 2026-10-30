import { useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRemoveSoftware, useRestoreSoftware, useRun, useStartRun, useWatchlist } from '../../api/queries'
import type { LastCheckView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconExternal } from '../../ui/icons'
import { AddSoftware } from './AddSoftware'
import { pressCheckNow } from './checkNow'
import { FindSoftware } from './FindSoftware'
import { Schedule } from './Schedule'
import { changeFeedback, NO_FEEDBACK, noticeButtons, noticeWords, pressRemove, pressUndo, PROBLEM_ID, removeButtonId, UNDO_ID, type ChangeFeedback, type Named } from './removal'
import { SoftwareHistory } from './SoftwareHistory'
import { cantCheckWords, countIn, emptyWords, groupsOf, newestOf, scheduleRuns, singaporeTime, statusLabel, statusTone, stoppedWords, versionSourceWords } from './software'
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
  readonly nameOf: (id: string) => string
  readonly onToggle: () => void
  readonly onRemove: () => void
}

function Row({ row, operator, scheduled, paused, open, removing, nameOf, onToggle, onRemove }: RowProps) {
  const historyId = `history-${row.id}`
  const newest = newestOf(row)
  return (
    <li className={styles['row']} data-status={row.status}>
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
            {row.our_version ?? 'Not known yet'}
            <span className={styles['src']}>{versionSourceWords(row.our_version_source)}</span>
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
          {statusLabel[row.status]}
        </span>
        {row.status === 'cant_check' ? <span className={styles['src']}>{cantCheckWords(row.problem, { scheduled, paused })}</span> : null}
        {row.status === 'ticket_open' && row.open_ticket ? <span className={styles['src']}>{row.open_ticket}</span> : null}
        {row.status === 'awaiting_approval' && row.approval_id ? (
          <Link to={`/approvals/${row.approval_id}`} className={styles['src']}>
            Review and decide
          </Link>
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

interface SectionProps {
  readonly title: string
  readonly rows: readonly WatchedSoftwareView[]
  readonly operator: boolean
  readonly scheduled: boolean
  readonly paused: boolean
  readonly opened: string | null
  readonly removing: string | null
  readonly nameOf: (id: string) => string
  readonly onToggle: (id: string) => void
  readonly onRemove: (row: WatchedSoftwareView) => void
}

function Section({ title, rows, ...rest }: SectionProps) {
  if (rows.length === 0) return null
  return (
    <section className={styles['section']} aria-label={title}>
      <h2>
        {title} <span className={styles['count']}>{rows.length}</span>
      </h2>
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
            nameOf={rest.nameOf}
            onToggle={() => rest.onToggle(row.id)}
            onRemove={() => rest.onRemove(row)}
          />
        ))}
      </ul>
    </section>
  )
}

function CheckNow({ useCaseId }: { useCaseId: string }) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useNavigate()
  const words = useErrorWords()
  return (
    <div className={styles['checkNow']}>
      <Button variant="primary" loading={start.isPending} onClick={() => pressCheckNow(latch, start.mutate, useCaseId, (runId) => void navigate(`/runs/${runId}`))}>
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

interface NoticeProps {
  readonly feedback: ChangeFeedback
  readonly scheduled: boolean
  readonly paused: boolean
  readonly onUndo: (row: Named) => void
  readonly onDismiss: () => void
}

/** The status line stays on the page when it is empty, so a screen reader hears each new message. */
function Notice({ feedback, scheduled, paused, onUndo, onDismiss }: NoticeProps) {
  const { notice } = feedback
  const escape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') onDismiss()
  }
  return (
    <>
      <div className={styles['notice']}>
        <p role="status">{notice ? noticeWords(notice, { scheduled, paused }) : ''}</p>
        {notice ? (
          <div className={styles['actions']}>
            {noticeButtons(notice).map((label) =>
              label === 'Undo' && notice.kind === 'removed' ? (
                <Button key={label} id={UNDO_ID} loading={feedback.busy?.act === 'restore'} onClick={() => onUndo(notice.row)} onKeyDown={escape}>
                  Undo
                </Button>
              ) : (
                <Button key={label} onClick={onDismiss} onKeyDown={escape}>
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

function Loaded({ view, operator }: { view: WatchlistView | null; operator: boolean }) {
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const changes = useLatch()
  useFocusOnceRendered(feedback)

  function dismiss() {
    const next = document.getElementById('find-software') ?? document.querySelector<HTMLElement>('main h1')
    next?.focus()
    dispatch({ type: 'dismissed' })
  }

  const software = view?.software ?? []
  const scheduled = scheduleRuns(view?.schedule)
  const paused = view?.state === 'paused'
  const groups = groupsOf(software, query)
  const shown = countIn(groups)
  const searching = query.trim() !== ''

  return (
    <>
      {operator && view && !paused && software.length > 0 ? <CheckNow useCaseId={view.use_case_id} /> : null}
      {view?.last_check?.state === 'failed' ? <LastCheckStopped last={view.last_check} /> : null}
      {view ? <Schedule schedule={view.schedule} operator={operator} paused={paused} /> : null}
      <Notice feedback={feedback} scheduled={scheduled} paused={paused} onUndo={(row) => pressUndo(changes, restore.mutate, row, dispatch, words)} onDismiss={dismiss} />
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
      {[
        { title: 'Needs a person', rows: groups.needs },
        { title: 'Not checked yet', rows: groups.notChecked },
        { title: 'Up to date', rows: groups.upToDate },
      ].map(({ title, rows }) => (
        <Section
          key={title}
          title={title}
          rows={rows}
          operator={operator}
          scheduled={scheduled}
          paused={paused}
          opened={opened}
          removing={feedback.busy?.act === 'remove' ? feedback.busy.id : null}
          nameOf={nameOf}
          onToggle={(id) => setOpened((current) => (current === id ? null : id))}
          onRemove={(row) => pressRemove(changes, removal.mutate, row, dispatch, words)}
        />
      ))}
      {operator ? (
        <AddSoftware names={software.map((row) => row.name)} repos={software.map((row) => row.source.ref)} onAdded={(name) => dispatch({ type: 'added', name })} />
      ) : null}
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
  return <Loaded view={watchlist.data} operator={me.data.roles.includes('operator')} />
}
