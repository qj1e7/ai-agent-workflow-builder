import { useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { failureReasonLabel } from '../../api/labels'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRemoveSoftware, useRestoreSoftware, useRun, useStartRun, useWatchlist } from '../../api/queries'
import type { LastCheckView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconExternal } from '../../ui/icons'
import { AddSoftware } from './AddSoftware'
import { Schedule } from './Schedule'
import { board, EMPTY_BOARD, noticeWords, pressRemove, pressUndo, removeButtonId, UNDO_ID, type Board, type Named } from './removal'
import { SoftwareHistory } from './SoftwareHistory'
import { CANT_CHECK_WORDS, countIn, groupsOf, matches, singaporeTime, statusLabel, statusTone, stoppedWords, versionSourceWords } from './software'
import styles from './Software.module.css'

const REFRESH_MS = 15_000

/** Moves focus once the element the last change named is on the page, as when Undo brings a row back. */
function useFocusFrom(state: Board) {
  const moved = useRef<Board | null>(null)
  useEffect(() => {
    if (state.focus === null || moved.current === state) return
    const target = document.getElementById(state.focus)
    if (!target) return
    target.focus()
    moved.current = state
  })
}

function Row({ row, operator, open, removing, nameOf, onToggle, onRemove }: { row: WatchedSoftwareView; operator: boolean; open: boolean; removing: boolean; nameOf: (id: string) => string; onToggle: () => void; onRemove: () => void }) {
  const historyId = `history-${row.id}`
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
          <dd>{row.newest_version ?? (row.status === 'not_checked' ? 'Not checked yet' : 'Not known')}</dd>
        </div>
      </dl>
      <div className={styles['state']}>
        <span className={styles['pill']} data-tone={statusTone[row.status]}>
          {statusLabel[row.status]}
        </span>
        {row.status === 'cant_check' ? <span className={styles['src']}>{CANT_CHECK_WORDS}</span> : null}
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

function Section({ title, rows, ...rest }: { title: string; rows: readonly WatchedSoftwareView[]; operator: boolean; opened: string | null; removing: string | null; nameOf: (id: string) => string; onToggle: (id: string) => void; onRemove: (row: WatchedSoftwareView) => void }) {
  if (rows.length === 0) return null
  return (
    <section className={styles['section']} aria-label={title}>
      <h2>
        {title} <span className={styles['count']}>{rows.length}</span>
      </h2>
      <ul className={styles['list']}>
        {rows.map((row) => (
          <Row key={row.id} row={row} operator={rest.operator} open={rest.opened === row.id} removing={rest.removing === row.id} nameOf={rest.nameOf} onToggle={() => rest.onToggle(row.id)} onRemove={() => rest.onRemove(row)} />
        ))}
      </ul>
    </section>
  )
}

function CheckNow({ useCaseId }: { useCaseId: string }) {
  const start = useStartRun()
  const navigate = useNavigate()
  const words = useErrorWords()
  return (
    <div className={styles['checkNow']}>
      <Button
        variant="primary"
        loading={start.isPending}
        onClick={() => start.mutate({ useCaseId, idempotencyKey: newIdempotencyKey() }, { onSuccess: (started) => void navigate(`/runs/${started.run_id}`) })}
      >
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
  const reason = run.data?.state === 'failed' ? failureReasonLabel[run.data.reason] : null
  return (
    <div className={styles['stopped']}>
      <p>
        <b>{stoppedWords(reason)}</b> Started {singaporeTime(last.started_at)}, Singapore time.
      </p>
      <Link to={`/runs/${last.run_id}`}>Open the run</Link>
    </div>
  )
}

/** The status line stays on the page when it is empty, so a screen reader hears each new message. */
function Notice({ state, onUndo, onDismiss }: { state: Board; onUndo: (row: Named) => void; onDismiss: () => void }) {
  const { notice } = state
  const undoing = notice?.kind === 'removed' ? notice.row : null
  const escape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') onDismiss()
  }
  return (
    <>
      <div className={styles['notice']}>
        <p role="status">{notice ? noticeWords(notice) : ''}</p>
        {undoing ? (
          <div className={styles['actions']}>
            <Button id={UNDO_ID} loading={state.busy?.act === 'restore'} onClick={() => onUndo(undoing)} onKeyDown={escape}>
              Undo
            </Button>
            <Button onClick={onDismiss} onKeyDown={escape}>
              Dismiss
            </Button>
          </div>
        ) : null}
      </div>
      {state.problem ? (
        <p className={styles['error']} role="alert">
          {state.problem}
        </p>
      ) : null}
    </>
  )
}

function Loaded({ view, operator }: { view: WatchlistView | null; operator: boolean }) {
  const [query, setQuery] = useState('')
  const [opened, setOpened] = useState<string | null>(null)
  const [state, dispatch] = useReducer(board, EMPTY_BOARD)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const changes = useLatch()
  useFocusFrom(state)

  function dismiss() {
    const next = document.getElementById('find-software') ?? document.querySelector<HTMLElement>('main h1')
    next?.focus()
    dispatch({ type: 'dismissed' })
  }

  const software = view?.software ?? []
  const groups = groupsOf(software, query)
  const shown = countIn(groups)
  const searching = query.trim() !== ''

  return (
    <>
      {operator && view && software.length > 0 ? <CheckNow useCaseId={view.use_case_id} /> : null}
      {view?.last_check?.state === 'failed' ? <LastCheckStopped last={view.last_check} /> : null}
      {view ? <Schedule schedule={view.schedule} operator={operator} /> : null}
      <Notice state={state} onUndo={(row) => pressUndo(changes, restore.mutate, row, dispatch, words)} onDismiss={dismiss} />
      {software.length > 0 || searching ? (
        <div className={styles['find']}>
          <label htmlFor="find-software">Find software</label>
          <input id="find-software" type="search" value={query} placeholder="Find software" autoComplete="off" onChange={(event) => setQuery(event.target.value)} />
          <p className="visually-hidden" role="status">
            {searching ? matches(shown) : ''}
          </p>
        </div>
      ) : null}
      {software.length === 0 && !searching ? (
        <div className={styles['empty']}>
          <b>No software yet</b>
          <span>{operator ? 'Add the tools your team runs. Each one is checked at the next check.' : 'An Operator can add the tools your team runs.'}</span>
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
          opened={opened}
          removing={state.busy?.act === 'remove' ? state.busy.id : null}
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
