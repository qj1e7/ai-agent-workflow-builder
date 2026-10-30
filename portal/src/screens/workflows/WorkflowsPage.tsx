import { useEffect, useState, type CSSProperties } from 'react'
import { Link, NavigationType, useLocation, useNavigate, useNavigationType } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useUseCases } from '../../api/queries'
import type { Me, RunView, UseCaseView } from '../../api/types'
import { useMoveWorkflow } from '../../api/workflowQueries'
import { PageHead } from '../../shell/PageHead'
import { Button, ButtonLink } from '../../ui/Button'
import { useFocusWhenReady } from '../../ui/focus'
import { FROM_LIST } from '../../ui/fromList'
import { IconSearch } from '../../ui/icons'
import { Toast, UNDO_ID, type ToastMessage } from '../../ui/Toast'
import { useArrivalScroll } from './arrival'
import { Faces, StatusPills } from './Status'
import { agentsOf, changeProblem, FILTERS, lineWhen, nextRunWords, pressChange, rowsOf, runFact, type Filter, type Row, type Viewer } from './workflow'
import styles from './Workflows.module.css'

export const REFRESH_MS = 15_000

export const rowLinkId = (useCaseId: string) => `workflow-${useCaseId}`

export function viewerOf(me: Me): Viewer {
  return { id: me.id, operator: me.roles.includes('operator'), approver: me.roles.includes('approver') }
}

interface Deleted {
  readonly id: string
  readonly name: string
}

/** The workflow page hands over what it deleted in the router state, so the list can offer Undo. */
export function deletedIn(state: unknown): Deleted | null {
  if (typeof state !== 'object' || state === null || !('deleted' in state)) return null
  const { deleted } = state as { deleted: Partial<Deleted> | null }
  return typeof deleted?.id === 'string' && typeof deleted.name === 'string' ? { id: deleted.id, name: deleted.name } : null
}

type Note = { readonly kind: 'deleted'; readonly id: number; readonly row: Deleted } | { readonly kind: 'said'; readonly id: number; readonly text: string }

let notes = 0
/** Called from event handlers only, so each message gets a new id and a fresh clock. */
const said = (text: string): Note => ({ kind: 'said', id: ++notes, text })

const lowerFirst = (words: string) => words.charAt(0).toLowerCase() + words.slice(1)

function latestLine(latest: RunView | null, now: Date, nameOf: (id: string) => string): string {
  if (!latest) return 'No runs yet.'
  return `${lineWhen(latest.started_at, now)}: ${lowerFirst(runFact(latest, nameOf).words)}`
}

function nextLine(useCase: UseCaseView, now: Date): string {
  const next = nextRunWords(useCase, now)
  return next === 'Not scheduled' ? next : `Next: ${next}`
}

interface RowProps {
  readonly row: Row
  readonly index: number
  readonly primary: boolean
  readonly arrive: boolean
  readonly now: Date
  readonly nameOf: (id: string) => string
}

function WorkflowRow({ row, index, primary, arrive, now, nameOf }: RowProps) {
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
        <h2>
          <Link id={rowLinkId(useCase.use_case_id)} to={`/workflows/${useCase.use_case_id}`} state={FROM_LIST} className={styles['rowLink']}>
            {useCase.name}
          </Link>
        </h2>
        <p>{latestLine(latest, now, nameOf)}</p>
      </div>
      <Faces agents={agentsOf(useCase)} useCase={useCase} latest={latest} />
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
    <div className={styles['findbar']}>
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
      <b>No workflows yet</b>
      {operator ? 'Once a workflow is set up, it shows here.' : 'An Operator sets them up. You approve their changes.'}
    </p>
  )
}

/** Hands the router state over once, so Back or a reload never offers the same Undo again. */
function useHandOver(): Deleted | null {
  const location = useLocation()
  const navigate = useNavigate()
  const [deleted] = useState(() => deletedIn(location.state))
  useEffect(() => {
    if (deletedIn(location.state)) void navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [location.state, location.pathname, location.search, navigate])
  return deleted
}

interface LoadedProps {
  readonly heading: string
  readonly lead: string
  readonly now: Date
  readonly me: Me
  readonly useCases: readonly UseCaseView[]
  readonly runs: readonly RunView[]
  readonly runsFailed: boolean
}

function Loaded({ heading, lead, now, me, useCases, runs, runsFailed }: LoadedProps) {
  const handedOver = useHandOver()
  const back = useNavigationType() === NavigationType.Pop
  const [note, setNote] = useState<Note | null>(() => (handedOver ? { kind: 'deleted', id: 0, row: handedOver } : null))
  const [problem, setProblem] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [restored, setRestored] = useState<string | null>(null)
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const move = useMoveWorkflow()
  const changes = useLatch()
  const viewer = viewerOf(me)
  useArrivalScroll(true)

  const focusRestored = useFocusWhenReady(restored !== null && useCases.some((item) => item.use_case_id === restored), () =>
    document.getElementById(rowLinkId(restored ?? '')),
  )

  useEffect(() => {
    if (handedOver) document.getElementById(UNDO_ID)?.focus()
  }, [handedOver])

  const rows = rowsOf(useCases, runs, viewer, filter, query)
  const firstAction = rows.findIndex((row) => row.action !== null)

  function undo(row: Deleted) {
    pressChange(changes, (outcome) => move.mutate({ move: 'restore', useCaseId: row.id }, outcome), {
      onSuccess: () => {
        setProblem(null)
        setRestored(row.id)
        focusRestored()
        setNote(said(`Put ${row.name} back.`))
      },
      onError: (error) => setProblem(changeProblem('restore', row.name, error, words)),
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
      <PageHead heading={heading} lead={lead} movesFocus={handedOver !== null} />
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      {runsFailed ? <p className={styles['problem']}>The latest runs could not be loaded, so each workflow shows none. They load again in a moment.</p> : null}
      {useCases.length > 0 ? <FindBar query={query} filter={filter} onQuery={setQuery} onFilter={setFilter} /> : <Empty operator={viewer.operator} />}
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
      <Toast
        message={message}
        onDismiss={() => setNote(null)}
        focusAfter={() => document.getElementById('find-workflows') ?? document.querySelector<HTMLElement>('main h1')}
      />
    </>
  )
}

export function WorkflowsPage({ heading, lead, now }: { heading: string; lead: string; now: Date }) {
  const me = useMe()
  const useCases = useUseCases()
  const runs = useRuns({ poll: REFRESH_MS })
  if ((useCases.isError && !useCases.data) || me.isError) {
    return (
      <>
        <PageHead heading={heading} lead={lead} />
        <p>The workflows could not be loaded.</p>
        <Button onClick={() => void Promise.all([useCases.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (!useCases.data || !me.data || (runs.isPending && !runs.isError)) {
    return (
      <>
        <PageHead heading={heading} lead={lead} />
        <p className="muted" role="status">
          Loading the workflows
        </p>
      </>
    )
  }
  return <Loaded heading={heading} lead={lead} now={now} me={me.data} useCases={useCases.data} runs={runs.data ?? []} runsFailed={runs.isError && !runs.data} />
}
