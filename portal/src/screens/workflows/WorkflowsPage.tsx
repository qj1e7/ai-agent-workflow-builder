import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, NavigationType, useLocation, useNavigate, useNavigationType, useSearchParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useHome } from '../../api/homeQueries'
import { useDeleteDraft, useDrafts, useSaveDraft } from '../../api/newQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useUseCases } from '../../api/queries'
import type { DraftView, HomeOut, Me, RunView, UseCaseView } from '../../api/types'
import { useMoveWorkflow, useRereadWorkflow } from '../../api/workflowQueries'
import { PageHead } from '../../shell/PageHead'
import { Button, ButtonLink } from '../../ui/Button'
import { useFocusWhenReady } from '../../ui/focus'
import { FROM_LIST } from '../../ui/fromList'
import { IconSearch, IconX } from '../../ui/icons'
import { Toast, UNDO_ID, type ToastMessage } from '../../ui/Toast'
import { moreWords, needsOf, needsTotal, runsInNeeds } from '../home/home'
import { NeedsSection, useArrival } from '../home/NeedsSection'
import homeStyles from '../home/Home.module.css'
import { useArrivalScroll } from './arrival'
import { StatusPills } from './Status'
import { RequestView } from './RequestView'
import { REQUEST_PARAM } from './requests'
import { DiscardDialog, DraftsSection, draftItem, FollowingSection, WaitingSection } from './Sections'
import { changeProblem, changeWords, FILTERS, meansOutOfDate, nextRunWords, pressChange, REFRESH_MS, rowsOf, runFact, viewerOf, workflowPath, type Filter, type Row } from './workflow'
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

type Note =
  | { readonly kind: 'deleted'; readonly id: number; readonly row: Deleted }
  | { readonly kind: 'discarded'; readonly id: number; readonly draft: DraftView }
  | { readonly kind: 'said'; readonly id: number; readonly text: string }

const PURPOSE_SHOWN = 110

function purposeOf(useCase: UseCaseView): string {
  const flat = useCase.instruction.replace(/\s+/g, ' ').trim()
  return flat.length > PURPOSE_SHOWN ? `${flat.slice(0, PURPOSE_SHOWN - 1).trimEnd()}…` : flat
}

function nextLine(useCase: UseCaseView, now: Date): string {
  const words = nextRunWords(useCase, now)
  const unscheduled = useCase.state === 'on' && useCase.next_run_at === null
  return unscheduled ? words : `Next: ${words}`
}

interface RowProps {
  readonly row: Row
  readonly index: number
  readonly primary: boolean
  readonly arrive: boolean
  readonly now: Date
  readonly nameOf: (id: string) => string
}

export function WorkflowRow({ row, index, primary, arrive, now, nameOf }: RowProps) {
  const { useCase, latest, action } = row
  const fact = latest ? runFact(latest, nameOf) : null
  return (
    <li
      className={arrive ? `${styles['row']} ${styles['arrive']}` : styles['row']}
      style={{ '--i': index } as CSSProperties}
      data-workflow-id={useCase.use_case_id}
      data-paused={useCase.state === 'paused' || undefined}
    >
      <StatusPills state={useCase.state} fact={fact} />
      <div className={styles['main']}>
        <h3>
          <Link id={rowLinkId(useCase.use_case_id)} to={workflowPath(useCase)} state={FROM_LIST} className={styles['rowLink']}>
            {useCase.name}
          </Link>
        </h3>
        <p>{purposeOf(useCase)}</p>
      </div>
      <div className={styles['foot']}>
        <span className={styles['next']}>{nextLine(useCase, now)}</span>
        <span className={styles['act']}>
          {action ? (
            <ButtonLink to={`/runs/${action.runId}`} variant={primary ? 'primary' : 'secondary'}>
              {action.kind === 'decide' ? 'Review and decide' : 'See why it stopped'}
            </ButtonLink>
          ) : null}
        </span>
      </div>
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
      {operator ? 'Ask the Planner on Home, and your first workflow shows up here.' : 'Operators set up workflows, and you approve their changes.'}
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

interface LoadedProps {
  readonly handedOver: Deleted | null
  readonly now: Date
  readonly me: Me
  readonly useCases: readonly UseCaseView[]
  readonly runs: readonly RunView[]
  readonly runsFailed: boolean
}

function Loaded({ handedOver, now, me, useCases, runs, runsFailed }: LoadedProps) {
  const back = useNavigationType() === NavigationType.Pop
  const [note, setNote] = useState<Note | null>(() => (handedOver ? { kind: 'deleted', id: 0, row: handedOver } : null))
  const [problem, setProblem] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [finding, setFinding] = useState(false)
  const [restored, setRestored] = useState<string | null>(null)
  const [restoredDraft, setRestoredDraft] = useState<string | null>(null)
  const [discarding, setDiscarding] = useState<DraftView | null>(null)
  const [discardProblem, setDiscardProblem] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const removeDraft = useDeleteDraft()
  const saveDraft = useSaveDraft()
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
  const drafts = useDrafts(viewer.operator).data
  const focusRestoredDraft = useFocusWhenReady(restoredDraft !== null && (drafts ?? []).some((draft) => draft.draft_id === restoredDraft), () =>
    document.querySelector<HTMLElement>(`[data-draft="${restoredDraft ?? ''}"] a`),
  )

  useEffect(() => {
    if (handedOver) document.getElementById(UNDO_ID)?.focus()
  }, [handedOver])

  useEffect(() => {
    if (finding) document.getElementById('find-workflows')?.focus()
  }, [finding])

  const noteKind = note?.kind
  const noteId = note?.id
  useEffect(() => {
    if (noteKind === 'discarded') document.getElementById(UNDO_ID)?.focus()
  }, [noteKind, noteId])

  const inNeeds = useMemo(() => (home ? runsInNeeds(home) : undefined), [home])
  const needsCard = home !== undefined && needsTotal(home) > 0
  const rows = rowsOf(useCases, runs, viewer, filter, query, inNeeds)
  const firstAction = needsCard ? -1 : rows.findIndex((row) => row.action !== null)

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

  const rereadDrafts = () => void queryClient.invalidateQueries({ queryKey: ['drafts'] })

  function confirmDiscard(draft: DraftView) {
    pressChange(changes, (outcome) => removeDraft.mutate(draft.draft_id, outcome), {
      onSuccess: () => {
        setDiscarding(null)
        setDiscardProblem(null)
        rereadDrafts()
        setNote((before) => ({ kind: 'discarded', id: (before?.id ?? 0) + 1, draft }))
      },
      onError: (error) => setDiscardProblem(`Could not discard it. ${words(error)}`),
    })
  }

  function putDraftBack(draft: DraftView) {
    pressChange(changes, (outcome) => saveDraft.mutate({ draftId: draft.draft_id, draft: { step: draft.step, content: draft.content, put_back: { created_at: draft.created_at, saved_at: draft.saved_at } } }, outcome), {
      onSuccess: () => {
        setProblem(null)
        setRestoredDraft(draft.draft_id)
        focusRestoredDraft()
        rereadDrafts()
        setNote((before) => ({ kind: 'said', id: (before?.id ?? 0) + 1, text: 'Put back.' }))
      },
      onError: (error) => setProblem(`Could not put ${draftItem(draft).name ?? 'New workflow'} back. ${words(error)}`),
    })
  }

  const message: ToastMessage | null =
    note?.kind === 'deleted'
      ? { id: note.id, text: `Deleted ${note.row.name}.`, undo: { busy: move.isPending, onPress: () => undo(note.row) } }
      : note?.kind === 'discarded'
        ? { id: note.id, text: `Discarded ${draftItem(note.draft).name ?? 'New workflow'}.`, undo: { busy: saveDraft.isPending, onPress: () => putDraftBack(note.draft) } }
        : note
          ? { id: note.id, text: note.text }
          : null

  const searching = query.trim() !== '' || filter !== 'all'
  const showFind = finding || searching

  function toggleFind() {
    if (showFind) {
      setFinding(false)
      setQuery('')
      setFilter('all')
    } else setFinding(true)
  }
  return (
    <>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      {runsFailed ? <p className={styles['problem']}>The latest runs could not be loaded, so each workflow shows none. They load again in a moment.</p> : null}
      {viewer.operator && drafts ? <DraftsSection drafts={drafts} now={now} onDiscard={(draft) => { setDiscardProblem(null); setDiscarding(draft) }} /> : null}
      {home ? <WaitingSection items={home.waiting_on_others} total={home.waiting_on_others_total} now={now} /> : null}
      {home ? <FollowingSection items={home.following_up} total={home.following_up_total} now={now} meId={me.id} /> : null}
      <section className={homeStyles['section']} aria-labelledby="all-workflows-h">
        <h2 id="all-workflows-h">
          All workflows <span className={homeStyles['count']}>{useCases.length}</span>
          {useCases.length > 0 ? (
            <button type="button" className={styles['searchButton']} aria-expanded={showFind} aria-controls="findbar-workflows" aria-label={showFind ? 'Hide search' : 'Search workflows'} onClick={toggleFind}>
              {showFind ? <IconX size={18} /> : <IconSearch size={18} />}
            </button>
          ) : null}
        </h2>
        {useCases.length > 0 && showFind ? <FindBar query={query} filter={filter} onQuery={setQuery} onFilter={setFilter} /> : null}
        {useCases.length === 0 ? <Empty operator={viewer.operator} /> : null}
        {useCases.length > 0 && rows.length === 0 && searching ? (
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
        {rows.length > 0 ? (
          <ul className={styles['list']} aria-label="Workflows">
            {rows.map((row, index) => (
              <WorkflowRow key={row.useCase.use_case_id} row={row} index={index} primary={index === firstAction} arrive={!back} now={now} nameOf={nameOf} />
            ))}
          </ul>
        ) : null}
      </section>
      {discarding ? (
        <DiscardDialog
          name={draftItem(discarding).name ?? 'New workflow'}
          busy={removeDraft.isPending}
          problem={discardProblem}
          onClose={() => {
            setDiscarding(null)
            setDiscardProblem(null)
          }}
          onConfirm={() => confirmDiscard(discarding)}
        />
      ) : null}
      <Toast
        message={message}
        onDismiss={() => setNote(null)}
        focusAfter={() => document.getElementById('find-workflows') ?? document.querySelector<HTMLElement>('main h1')}
      />
    </>
  )
}

function NeedsYou({ now }: { now: Date }) {
  const home = useHome()
  return home.data ? <NeedsYouLoaded home={home.data} now={now} /> : null
}

function NeedsYouLoaded({ home, now }: { home: HomeOut; now: Date }) {
  const needs = useMemo(() => needsOf(home), [home])
  const arrival = useArrival(needs.shown.map((need) => need.key))
  const more = moreWords(needs.more)
  return (
    <div className={styles['needsYou']}>
      <NeedsSection needs={needs} now={now} arrival={arrival} more={more ? <p className={homeStyles['more']}>{more}</p> : null} whenNone={null} />
    </div>
  )
}

export function WorkflowsPage({ heading, lead, now }: { heading: string; lead: string; now: Date }) {
  const handedOver = useDeletedHandedOverOnce()
  const requestId = useSearchParams()[0].get(REQUEST_PARAM)
  return (
    <>
      <PageHead heading={heading} lead={lead} movesFocus={handedOver !== null} />
      {requestId !== null ? (
        <RequestView key={requestId} requestId={requestId} now={now} />
      ) : (
        <>
          <NeedsYou now={now} />
          <WorkflowsBody handedOver={handedOver} now={now} />
        </>
      )}
    </>
  )
}

function WorkflowsBody({ handedOver, now }: { handedOver: Deleted | null; now: Date }) {
  const me = useMe()
  const useCases = useUseCases()
  const runs = useRuns({ poll: REFRESH_MS })
  if ((useCases.isError && !useCases.data) || me.isError) {
    return (
      <>
        <p>The workflows could not be loaded.</p>
        <Button onClick={() => void Promise.all([useCases.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (!useCases.data || !me.data || (runs.isPending && !runs.isError)) {
    return (
      <p className="muted" role="status">
        Loading the workflows
      </p>
    )
  }
  return <Loaded handedOver={handedOver} now={now} me={me.data} useCases={useCases.data} runs={runs.data ?? []} runsFailed={runs.isError && !runs.data} />
}
