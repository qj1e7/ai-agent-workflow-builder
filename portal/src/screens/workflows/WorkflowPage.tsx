import { useEffect, useId, useRef, useState, type MouseEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useStartRun, useUseCase } from '../../api/queries'
import type { Me, UseCaseView } from '../../api/types'
import { useDeleteWorkflow, useMoveWorkflow } from '../../api/workflowQueries'
import { PageHead } from '../../shell/PageHead'
import { AgentFace } from '../../ui/AgentFace'
import { Button, ButtonLink } from '../../ui/Button'
import { FROM_LIST, openedFromList } from '../../ui/fromList'
import { IconChevronLeft, IconPause, IconPlay, IconTrash } from '../../ui/icons'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { useArrivalScroll } from './arrival'
import { RecentRuns } from './RecentRuns'
import { StatusPills, useChanges } from './Status'
import {
  agentsOf,
  changeProblem,
  changeWords,
  controlsOf,
  nextRunWords,
  pressChange,
  pressRunNow,
  rowAction,
  runFact,
  runsOf,
  SOFTWARE_PAGE,
  stepTag,
  whenWords,
  workflowPath,
} from './workflow'
import { REFRESH_MS, viewerOf } from './WorkflowsPage'
import styles from './Workflows.module.css'

export const WHO_APPROVES = 'Any Approver except the people who start or own it'

function BackToList() {
  const location = useLocation()
  const navigate = useNavigate()
  const goBack = (event: MouseEvent) => {
    if (!openedFromList(location.state)) return
    event.preventDefault()
    void navigate(-1)
  }
  return (
    <Link to="/workflows" className={styles['back']} onClick={goBack}>
      <IconChevronLeft size={16} />
      Workflows
    </Link>
  )
}

function When({ useCase }: { useCase: UseCaseView }) {
  const { words, small } = whenWords(useCase)
  return (
    <dd>
      {words}
      <small>{small}</small>
    </dd>
  )
}

function NextRun({ useCase, now }: { useCase: UseCaseView; now: Date }) {
  const words = nextRunWords(useCase, now)
  const changes = useChanges(words)
  return (
    <dd>
      <span key={changes} className={changes > 0 ? styles['changed'] : undefined}>
        {words}
      </span>
    </dd>
  )
}

function Steps({ useCase }: { useCase: UseCaseView }) {
  const headingId = useId()
  return (
    <section className={styles['panel']} aria-labelledby={headingId}>
      <h2 id={headingId}>What it does</h2>
      <ol className={styles['steps']}>
        {useCase.plan.map((block) => {
          const tag = stepTag(block.kind)
          return (
            <li key={block.key}>
              <div>
                <div className={styles['what']}>{block.name}</div>
                <p className={styles['how']}>{block.description}</p>
                <span className={styles['tag']} data-writes={tag.writes || undefined}>
                  {tag.words}
                </span>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

interface DeleteDialogProps {
  readonly name: string
  readonly busy: boolean
  readonly problem: string | null
  readonly onClose: () => void
  readonly onConfirm: () => void
}

function DeleteDialog({ name, busy, problem, onClose, onConfirm }: DeleteDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const textId = useId()
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    cancel.current?.focus()
  }, [])
  return (
    <dialog ref={dialog} className={styles['dialog']} role="alertdialog" aria-labelledby={titleId} aria-describedby={textId} onClose={onClose}>
      <h2 id={titleId}>Delete {name}?</h2>
      <p id={textId}>It stops running and leaves Workflows. Its past runs stay in the record.</p>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <div className={styles['btns']}>
        <Button ref={cancel} onClick={() => dialog.current?.close()}>
          Cancel
        </Button>
        <Button variant="danger-outline" icon={IconTrash} loading={busy} onClick={onConfirm}>
          Delete workflow
        </Button>
      </div>
    </dialog>
  )
}

function useRunNow(useCaseId: string) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useNavigate()
  const [key, setKey] = useState(newIdempotencyKey)
  const press = () =>
    pressRunNow(latch, start.mutate, { useCaseId, idempotencyKey: key }, (runId) => {
      setKey(newIdempotencyKey())
      void navigate(`/runs/${runId}`)
    })
  return { press, pending: start.isPending, error: start.error, reset: start.reset }
}

interface Said {
  readonly id: number
  readonly text: string
}

function WorkflowView({ useCase, me, now }: { useCase: UseCaseView; me: Me; now: Date }) {
  const id = useCase.use_case_id
  const runs = useRuns({ poll: REFRESH_MS })
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const navigate = useNavigate()
  const viewer = viewerOf(me)
  const move = useMoveWorkflow()
  const removal = useDeleteWorkflow()
  const changes = useLatch()
  const runNow = useRunNow(id)
  const deleteButton = useRef<HTMLButtonElement>(null)
  const [asking, setAsking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [deleteProblem, setDeleteProblem] = useState<string | null>(null)
  const [said, setSaid] = useState<Said | null>(null)
  useArrivalScroll()

  const recent = runsOf(runs.data ?? [], id)
  const latest = recent[0] ?? null
  const fact = latest ? runFact(latest, nameOf) : null
  const action = rowAction(useCase, latest, viewer)
  const paused = useCase.state === 'paused'
  const controls = controlsOf(useCase, viewer)
  const onOff = controls.find((control) => control === 'pause' || control === 'resume')

  function pauseOrResume(what: 'pause' | 'resume') {
    pressChange(changes, (outcome) => move.mutate({ move: what, useCaseId: id }, outcome), {
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        runNow.reset()
        setSaid((before) => ({ id: (before?.id ?? 0) + 1, text: changeWords(what, view, now) }))
      },
      onError: (error) => setProblem(changeProblem(what, useCase.name, error, words)),
    })
  }

  function confirmDelete() {
    pressChange(changes, (outcome) => removal.mutate(id, outcome), {
      onSuccess: () => void navigate('/workflows', { state: { deleted: { id, name: useCase.name } } }),
      onError: (error) => setDeleteProblem(changeProblem('delete', useCase.name, error, words)),
    })
  }

  const message: ToastMessage | null = said ? { id: said.id, text: said.text } : null
  const runNowVariant = action ? 'secondary' : 'primary'
  return (
    <>
      <BackToList />
      <div className={styles['head']}>
        <div>
          <StatusPills state={useCase.state} fact={fact} />
          <h1 tabIndex={-1}>{useCase.name}</h1>
          <p>{useCase.instruction}</p>
        </div>
        <div className={styles['btns']}>
          {action ? (
            <ButtonLink to={`/runs/${action.runId}`} variant="primary">
              {action.kind === 'decide' ? 'Review and decide' : 'See why it stopped'}
            </ButtonLink>
          ) : null}
          {controls.includes('run') ? (
            <Button variant={runNowVariant} loading={runNow.pending} onClick={runNow.press}>
              Run now
            </Button>
          ) : null}
        </div>
      </div>
      {runNow.error ? (
        <p className={styles['problem']} role="alert">
          {words(runNow.error)}
        </p>
      ) : null}
      {controls.length > 0 ? (
        <div className={styles['btns']}>
          {onOff ? (
            <Button icon={onOff === 'resume' ? IconPlay : IconPause} loading={move.isPending} onClick={() => pauseOrResume(onOff)}>
              {onOff === 'resume' ? 'Resume' : 'Pause'}
            </Button>
          ) : null}
          {controls.includes('delete') ? (
            <Button
              ref={deleteButton}
              variant="danger-outline"
              icon={IconTrash}
              onClick={() => {
                setDeleteProblem(null)
                setAsking(true)
              }}
            >
              Delete
            </Button>
          ) : null}
        </div>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <dl className={styles['facts']}>
        <div>
          <dt>When</dt>
          <When useCase={useCase} />
        </div>
        <div>
          <dt>Next run</dt>
          <NextRun useCase={useCase} now={now} />
        </div>
        <div>
          <dt>Who approves</dt>
          <dd>
            {WHO_APPROVES}
            <small>Owned by {nameOf(useCase.owner)}.</small>
          </dd>
        </div>
        <div className={styles['wide']}>
          <dt>Agents</dt>
          <dd>
            <span className={styles['chips']}>
              {agentsOf(useCase).map((agent) => (
                <Link key={agent.to} to={agent.to} state={FROM_LIST} className={styles['chip']}>
                  <AgentFace id={agent.face} display={agent.name} size={28} state={paused ? 'stopped' : 'idle'} />
                  {agent.name}
                </Link>
              ))}
            </span>
          </dd>
        </div>
      </dl>
      <div className={styles['body']}>
        <Steps useCase={useCase} />
        {runs.data ? (
          <RecentRuns runs={recent} now={now} nameOf={nameOf} firstRun={useCase.next_run_at && !paused ? nextRunWords(useCase, now) : null} />
        ) : (
          <section className={styles['panel']}>
            <h2>Recent runs</h2>
            {runs.isError ? (
              <p>
                The runs could not be loaded. <Button onClick={() => void runs.refetch()}>Try again</Button>
              </p>
            ) : (
              <p className="muted" role="status">
                Loading the runs
              </p>
            )}
          </section>
        )}
      </div>
      {asking ? (
        <DeleteDialog
          name={useCase.name}
          busy={removal.isPending}
          problem={deleteProblem}
          onClose={() => {
            setAsking(false)
            deleteButton.current?.focus()
          }}
          onConfirm={confirmDelete}
        />
      ) : null}
      <Toast message={message} onDismiss={() => setSaid(null)} focusAfter={() => document.querySelector<HTMLElement>('main h1')} />
    </>
  )
}

function notFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

function WorkflowLoader({ useCaseId, now }: { useCaseId: string; now: Date }) {
  const useCase = useUseCase(useCaseId)
  const me = useMe()
  if (useCase.isError && notFound(useCase.error)) {
    return (
      <>
        <PageHead heading="Workflow not found" lead="It is not on the list. It may have been deleted." />
        <p>
          <Link to="/workflows">Go to Workflows</Link>
        </p>
      </>
    )
  }
  if (useCase.isError || me.isError) {
    return (
      <>
        <PageHead heading="Could not load the workflow" lead="The platform did not answer as it should." />
        <Button onClick={() => void Promise.all([useCase.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (!useCase.data || !me.data) {
    return (
      <p className="muted" role="status">
        Loading the workflow
      </p>
    )
  }
  if (workflowPath(useCase.data) === SOFTWARE_PAGE) return <Navigate to={SOFTWARE_PAGE} replace />
  return <WorkflowView useCase={useCase.data} me={me.data} now={now} />
}

export function WorkflowRoute({ now }: { now: Date }) {
  const { useCaseId = '' } = useParams()
  return <WorkflowLoader key={useCaseId} useCaseId={useCaseId} now={now} />
}
