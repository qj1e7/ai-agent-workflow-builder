import { useEffect, useId, useMemo, useState, type CSSProperties } from 'react'
import { NavigationType, useLocation, useNavigate, useNavigationType, useSearchParams } from 'react-router'
import { Link } from '../../ui/Link'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isOperator } from '../../api/me'
import { useHome } from '../../api/homeQueries'
import { useDrafts } from '../../api/plannerQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useUseCases } from '../../api/queries'
import type { DraftView, Me, UseCaseView } from '../../api/types'
import { useMoveWorkflow, useRereadWorkflow } from '../../api/workflowQueries'
import { OperatorsNote } from '../../shell/OperatorsNote'
import { PageHead, PageNote } from '../../shell/PageHead'
import { Button } from '../../ui/Button'
import { useFocusWhenReady } from '../../ui/focus'
import { FROM_LIST } from '../../ui/fromList'
import { IconSearch } from '../../ui/icons'
import { OpenLink } from '../../ui/OpenItem'
import { Toast, UNDO_ID, type ToastMessage } from '../../ui/Toast'
import { draftPath, savedLeft } from '../home/card'
import { draftWords, moreWords, needsOf } from '../home/home'
import { NeedRows } from '../home/NeedsSection'
import { useArrivalScroll } from './arrival'
import { StatusPills } from './Status'
import { RequestView } from './RequestView'
import { REQUEST_PARAM } from './requests'
import { draftItem, FollowingSection } from './Sections'
import { changeProblem, changeWords, FILTERS, meansOutOfDate, pillOf, pressChange, REFRESH_MS, rowLine, rowsOf, SOFTWARE_PAGE, viewerOf, workflowPath, type Filter, type Row } from './workflow'
import styles from './Workflows.module.css'

export const rowLinkId = (useCaseId: string) => `workflow-${useCaseId}`

interface Deleted {
  readonly id: string
  readonly name: string
}

export function deletedIn(state: unknown): Deleted | null {
  if (typeof state !== 'object' || state === null || !('deleted' in state)) return null
  const { deleted } = state as { deleted: Partial<Deleted> | null }
  return typeof deleted?.id === 'string' && typeof deleted.name === 'string' ? { id: deleted.id, name: deleted.name } : null
}

type Note = { readonly kind: 'deleted'; readonly id: number; readonly row: Deleted } | { readonly kind: 'said'; readonly id: number; readonly text: string }

/** More rows than this and the list gets its search box and filters. */
export const SEARCH_AFTER = 10

interface RowProps {
  readonly row: Row
  readonly index: number
  /** Unused: a row is one link and carries no button. The chat's check card still passes it. */
  readonly primary?: boolean
  readonly arrive: boolean
  readonly now: Date
  readonly nameOf: (id: string) => string
}

/** The list's class. */
export const listClass = (_rows: readonly Row[], extra = ''): string => [styles['list'], extra].filter(Boolean).join(' ')

/**
 * One workflow, as the sketch draws it: its name, "Daily 8:00 · last run today, {where it stands}", and one pill. The whole row is one link of 44 px or more.
 * In the chat it opens the workflow in the side panel. The Software watchlist always opens its page.
 */
export function WorkflowRow({ row, index, arrive, now, nameOf }: RowProps) {
  const { useCase } = row
  const path = workflowPath(useCase)
  const item = { kind: 'workflow', id: useCase.use_case_id } as const
  const ids = useId()
  const link = { 'aria-labelledby': `${ids}-name`, 'aria-describedby': `${ids}-pill ${ids}-sub` }
  const inside = (
    <>
      <span className={styles['main']}>
        <b id={`${ids}-name`}>{useCase.name}</b>
        <span id={`${ids}-sub`} className={styles['sub']}>
          {rowLine(useCase, now, nameOf)}
        </span>
      </span>
      <span id={`${ids}-pill`}>
        <StatusPills state={useCase.state} fact={useCase.last_run ? pillOf(useCase.last_run) : null} test={useCase.last_run?.test === true} />
      </span>
    </>
  )
  return (
    <li
      className={arrive ? `${styles['row']} ${styles['arrive']}` : styles['row']}
      style={{ '--i': index } as CSSProperties}
      data-workflow-id={useCase.use_case_id}
      data-paused={useCase.state === 'paused' || undefined}
    >
      {path === SOFTWARE_PAGE ? (
        <Link id={rowLinkId(useCase.use_case_id)} to={path} state={FROM_LIST} className={styles['rowLink']} {...link}>
          {inside}
        </Link>
      ) : (
        <OpenLink item={item} id={rowLinkId(useCase.use_case_id)} to={path} state={FROM_LIST} className={styles['rowLink']} {...link}>
          {inside}
        </OpenLink>
      )}
    </li>
  )
}

function FindBar({ query, filter, onQuery, onFilter }: { query: string; filter: Filter; onQuery: (query: string) => void; onFilter: (filter: Filter) => void }) {
  return (
    <div className={styles['findbar']} id="findbar-workflows">
      <span className={styles['findbox']}>
        <IconSearch size={18} />
        <label className="visually-hidden" htmlFor="find-workflows">
          Find a workflow
        </label>
        <input type="search" id="find-workflows" placeholder="Find a workflow" value={query} onChange={(event) => onQuery(event.target.value)} />
      </span>
      <div className={styles['filters']} role="group" aria-label="Show">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={filter === key} onClick={() => onFilter(key)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Empty({ operator }: { operator: boolean }) {
  return (
    <p className={styles['quiet']}>
      <b>Nothing here yet</b>
      {operator ? 'Watch software on the Watchlist, or ask the Planner in the chat. Its checks show up here.' : 'Operators set up workflows, and you approve their changes.'}
    </p>
  )
}

function useDeletedHandedOverOnce(): Deleted | null {
  const location = useLocation()
  const navigate = useNavigate()
  const [deleted] = useState(() => deletedIn(location.state))
  useEffect(() => {
    if (deletedIn(location.state)) void navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [location.state, location.pathname, location.search, navigate])
  return deleted
}

/**
 * Needs you, as the sketch draws it on Workflows: a heading, then Do now and Set up in the very rows Home and the strip read, so a row
 * says the same words in the same tone everywhere, and the strip's "N more" counts these rows. Nothing shows while nothing needs the person.
 */
function NeedsYou({ now }: { now: Date }) {
  const home = useHome().data
  const headingId = useId()
  const needs = useMemo(() => (home ? needsOf(home) : null), [home])
  if (!needs || needs.shown.length === 0) return null
  const more = moreWords(needs.more)
  return (
    <section className={styles['block']} aria-labelledby={headingId}>
      <h2 id={headingId}>Needs you</h2>
      <NeedRows needs={needs.shown} now={now} level={3} more={more ? <p className={styles['moreNote']}>{more}</p> : null} />
    </section>
  )
}

/** A saved draft, under All workflows like any workflow, with the pill Draft. It opens in the chat, where its card has Discard. */
function DraftRow({ draft, index, arrive, now }: { draft: DraftView; index: number; arrive: boolean; now: Date }) {
  const words = draftWords(draftItem(draft), now, savedLeft(draft))
  const ids = useId()
  return (
    <li className={arrive ? `${styles['row']} ${styles['arrive']}` : styles['row']} style={{ '--i': index } as CSSProperties} data-draft={draft.draft_id}>
      <Link to={draftPath(draft.draft_id)} className={styles['rowLink']} aria-labelledby={`${ids}-name`} aria-describedby={`${ids}-pill ${ids}-sub`}>
        <span className={styles['main']}>
          <b id={`${ids}-name`}>{words.name}</b>
          <span id={`${ids}-sub`} className={styles['sub']}>
            {words.sub}
          </span>
        </span>
        <span className={styles['pills']}>
          <span id={`${ids}-pill`} className={styles['pill']}>
            Draft
          </span>
        </span>
      </Link>
    </li>
  )
}

/** The drafts a search or a filter keeps: only All shows them, since a draft has not run and can't be paused. */
const draftsShown = (drafts: readonly DraftView[], filter: Filter, query: string): readonly DraftView[] => {
  const words = query.trim().toLowerCase()
  return filter === 'all' ? drafts.filter((draft) => (draftItem(draft).name ?? 'New workflow').toLowerCase().includes(words)) : []
}

interface LoadedProps {
  readonly handedOver: Deleted | null
  readonly now: Date
  readonly me: Me
  readonly useCases: readonly UseCaseView[]
}

function Loaded({ handedOver, now, me, useCases }: LoadedProps) {
  const back = useNavigationType() === NavigationType.Pop
  const [note, setNote] = useState<Note | null>(() => (handedOver ? { kind: 'deleted', id: 0, row: handedOver } : null))
  const [problem, setProblem] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [restored, setRestored] = useState<string | null>(null)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const move = useMoveWorkflow()
  const reread = useRereadWorkflow()
  const changes = useLatch()
  const viewer = viewerOf(me)
  useArrivalScroll()

  const focusRestored = useFocusWhenReady(restored !== null && useCases.some((item) => item.use_case_id === restored), () =>
    document.getElementById(rowLinkId(restored ?? '')),
  )

  const home = useHome().data
  const saved = useDrafts(viewer.operator).data
  const drafts = viewer.operator ? (saved ?? []) : []

  useEffect(() => {
    if (handedOver) document.getElementById(UNDO_ID)?.focus()
  }, [handedOver])

  const rows = rowsOf(useCases, viewer, filter, query)
  const draftRows = draftsShown(drafts, filter, query)
  const searchable = useCases.length > SEARCH_AFTER

  function undo(row: Deleted) {
    pressChange(changes, (outcome) => move.mutate({ move: 'restore', useCaseId: row.id }, outcome), {
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        setRestored(row.id)
        focusRestored()
        setNote((before) => ({ kind: 'said', id: (before?.id ?? 0) + 1, text: changeWords('restore', view, now) }))
      },
      onError: (error) => {
        if (meansOutOfDate(error)) reread(row.id)
        setProblem(changeProblem('restore', row.name, error, words))
      },
    })
  }

  const message: ToastMessage | null =
    note?.kind === 'deleted'
      ? { id: note.id, text: `Deleted ${note.row.name}.`, undo: { busy: move.isPending, onPress: () => undo(note.row) } }
      : note
        ? { id: note.id, text: note.text }
        : null

  const searching = query.trim() !== '' || filter !== 'all'
  return (
    <>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <NeedsYou now={now} />
      <section className={styles['block']} aria-labelledby="all-workflows-h">
        <h2 id="all-workflows-h">All workflows</h2>
        {searchable ? <FindBar query={query} filter={filter} onQuery={setQuery} onFilter={setFilter} /> : null}
        {useCases.length === 0 && drafts.length === 0 ? <Empty operator={viewer.operator} /> : null}
        {useCases.length + drafts.length > 0 && rows.length + draftRows.length === 0 && searching ? (
          <div className={styles['quiet']}>
            <b>No workflows match</b>
            Try other words, or see them all.
            <div>
              <Button
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                  document.getElementById('find-workflows')?.focus()
                }}
              >
                Show all workflows
              </Button>
            </div>
          </div>
        ) : null}
        {rows.length + draftRows.length > 0 ? (
          <ul className={listClass(rows)} aria-label="Workflows">
            {rows.map((row, index) => (
              <WorkflowRow key={row.useCase.use_case_id} row={row} index={index} arrive={!back} now={now} nameOf={nameOf} />
            ))}
            {draftRows.map((draft, index) => (
              <DraftRow key={draft.draft_id} draft={draft} index={rows.length + index} arrive={!back} now={now} />
            ))}
          </ul>
        ) : null}
      </section>
      {home ? <FollowingSection items={home.following_up} total={home.following_up_total} now={now} meId={me.id} /> : null}
      <Toast message={message} onDismiss={() => setNote(null)} focusAfter={() => document.getElementById('find-workflows') ?? document.querySelector<HTMLElement>('main h1')} />
    </>
  )
}

function ReadOnlyNote() {
  const me = useMe().data
  const listed = useUseCases().data ?? []
  return me && !isOperator(me) && listed.length > 0 ? (
    <PageNote>
      <OperatorsNote what="workflows" />
    </PageNote>
  ) : null
}

export function WorkflowsPage({ heading, now }: { heading: string; now: Date }) {
  const handedOver = useDeletedHandedOverOnce()
  const requestId = useSearchParams()[0].get(REQUEST_PARAM)
  return (
    <>
      <PageHead heading={heading} lead="" movesFocus={handedOver !== null}>
        {requestId === null ? <ReadOnlyNote /> : null}
      </PageHead>
      {requestId !== null ? <RequestView key={requestId} requestId={requestId} now={now} /> : <WorkflowsBody handedOver={handedOver} now={now} />}
    </>
  )
}

function WorkflowsBody({ handedOver, now }: { handedOver: Deleted | null; now: Date }) {
  const me = useMe()
  const useCases = useUseCases({ poll: REFRESH_MS })
  if ((useCases.isError && !useCases.data) || me.isError) {
    return (
      <>
        <p>The workflows could not be loaded.</p>
        <Button onClick={() => void Promise.all([useCases.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (!useCases.data || !me.data) {
    return (
      <p className="muted" role="status">
        Loading the workflows
      </p>
    )
  }
  return <Loaded handedOver={handedOver} now={now} me={me.data} useCases={useCases.data} />
}
