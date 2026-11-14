import { useEffect, useId, useRef, useState, type MouseEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useStartRun, useUseCase } from '../../api/queries'
import type { Me, UseCaseView } from '../../api/types'
import { useDeleteWorkflow, useMoveWorkflow, useRereadWorkflow } from '../../api/workflowQueries'
import { OperatorsNote } from '../../shell/OperatorsNote'
import { PageHead } from '../../shell/PageHead'
import { ActionMenu, type MenuItem } from '../../ui/ActionMenu'
import { Button } from '../../ui/Button'
import { useFocusAfterReread } from '../../ui/focus'
import { useFromChat } from '../../ui/fromChat'
import { openedFromList } from '../../ui/fromList'
import { IconChevronLeft, IconPause, IconPlay, IconTrash } from '../../ui/icons'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { RunLine } from '../run/RunLine'
import { StatusBanner } from './Banner'
import { useArrivalScroll } from './arrival'
import { templateLine } from './line'
import { RecentRuns } from './RecentRuns'
import { StatusPills } from './Status'
import { Versions } from './Versions'
import { DraftActions } from './DraftActions'
import { When } from './When'
import {
  bannerOf,
  changeProblem,
  changeWords,
  controlsOf,
  deleteWords,
  leftOutWords,
  mayChangeSchedule,
  menuActionsOf,
  nextRunWords,
  ownWorkRule,
  placeOf,
  PLACES_IN_PAGE_ORDER,
  pressChange,
  pressRunNow,
  REFRESH_MS,
  rereadWhenOutOfDate,
  pillOf,
  runsOf,
  sentenceOf,
  SOFTWARE_PAGE,
  viewerOf,
  whoSaysYes,
  workflowPath,
  type Place,
} from './workflow'
import styles from './Workflows.module.css'

function BackToList() {
  const location = useLocation()
  const navigate = useNavigate()
  const fromChat = useFromChat()
  const goBack = (event: MouseEvent) => {
    if (!openedFromList(location.state)) return
    event.preventDefault()
    void navigate(-1)
  }
  if (fromChat) return null
  return (
    <Link to="/workflows" className={styles['back']} onClick={goBack}>
      <IconChevronLeft size={16} />
      Workflows
    </Link>
  )
}

interface DeleteDialogProps {
  readonly name: string
  /** Null until the runs have loaded, when the dialog says nothing about them. */
  readonly pastRuns: number | null
  readonly busy: boolean
  readonly problem: string | null
  readonly onClose: () => void
  readonly onConfirm: () => void
}

function DeleteDialog({ name, pastRuns, busy, problem, onClose, onConfirm }: DeleteDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const textId = useId()
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    cancel.current?.focus()
  }, [])
  // The dialog's own close event arrives in a later task, after the next key press may have opened the menu behind it. So Escape and Cancel close it here and tell the page at once.
  const finish = () => {
    dialog.current?.close()
    onClose()
  }
  return (
    <dialog
      ref={dialog}
      className={styles['dialog']}
      role="alertdialog"
      aria-labelledby={titleId}
      aria-describedby={textId}
      onCancel={(event) => {
        event.preventDefault()
        finish()
      }}
    >
      <h2 id={titleId}>Delete {name}?</h2>
      <p id={textId}>{deleteWords(name, pastRuns)}</p>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <div className={styles['btns']}>
        <Button ref={cancel} onClick={finish}>
          Cancel
        </Button>
        <Button variant="danger-outline" icon={IconTrash} loading={busy} onClick={onConfirm}>
          Delete workflow
        </Button>
      </div>
    </dialog>
  )
}

function useRunNow(useCaseId: string, refused: (error: unknown) => void) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useNavigate()
  const [key, setKey] = useState(newIdempotencyKey)
  const open = (runId: string) => {
    setKey(newIdempotencyKey())
    void navigate(`/runs/${runId}`)
  }
  const press = () => pressRunNow(latch, start.mutate, { useCaseId, idempotencyKey: key }, { open, refused })
  return { press, pending: start.isPending, error: start.error, reset: start.reset }
}

interface Said {
  readonly id: number
  readonly text: string
}

interface ViewProps {
  readonly useCase: UseCaseView
  readonly me: Me
  readonly now: Date
  readonly onReread: (pressed: Place) => void
}

function WorkflowView({ useCase, me, now, onReread }: ViewProps) {
  const id = useCase.use_case_id
  const runs = useRuns({ poll: REFRESH_MS })
  const nameOf = useDisplayName()
  const words = useErrorWords()
  const navigate = useNavigate()
  const viewer = viewerOf(me)
  const move = useMoveWorkflow()
  const removal = useDeleteWorkflow()
  const reread = useRereadWorkflow()
  const changes = useLatch()
  const rereadIfOutOfDate = rereadWhenOutOfDate(id, onReread, reread)
  const runNow = useRunNow(id, rereadIfOutOfDate('more'))
  const moreButton = useRef<HTMLButtonElement>(null)
  const [asking, setAsking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [deleteProblem, setDeleteProblem] = useState<string | null>(null)
  const [said, setSaid] = useState<Said | null>(null)
  const switchedTo = useRef<UseCaseView['state'] | null>(null)
  useArrivalScroll()

  const recent = runsOf(runs.data ?? [], id)
  const paused = useCase.state === 'paused'
  const controls = controlsOf(useCase, viewer)
  const menuActions = menuActionsOf(useCase, viewer)
  const mayPause = controls.includes('pause')
  const banner = bannerOf({ useCase, viewer, now, nameOf })
  const gate = useCase.plan.some((block) => block.kind === 'approval')

  // The control that took the press leaves the page, so focus follows to its replacement: Resume in the banner, or Pause below.
  useEffect(() => {
    if (switchedTo.current !== useCase.state) return
    switchedTo.current = null
    document.querySelector<HTMLElement>('main [data-place="switch"]')?.focus()
  })

  function pauseOrResume(what: 'pause' | 'resume') {
    pressChange(changes, (outcome) => move.mutate({ move: what, useCaseId: id }, outcome), {
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        runNow.reset()
        switchedTo.current = view.state
        setSaid((before) => ({ id: (before?.id ?? 0) + 1, text: changeWords(what, view, now) }))
      },
      onError: (error) => {
        rereadIfOutOfDate('switch')(error)
        setProblem(changeProblem(what, useCase.name, error, words))
      },
    })
  }

  function confirmDelete() {
    pressChange(changes, (outcome) => removal.mutate(id, outcome), {
      onSuccess: () => void navigate('/workflows', { state: { deleted: { id, name: useCase.name } } }),
      onError: (error) => {
        rereadIfOutOfDate('more')(error)
        setDeleteProblem(changeProblem('delete', useCase.name, error, words))
      },
    })
  }

  const items: MenuItem[] = menuActions.flatMap((action): MenuItem[] => {
    switch (action) {
      case 'run':
        return [{ key: 'run', label: 'Run now', icon: IconPlay, onSelect: runNow.press }]
      case 'schedule':
        return []
      case 'delete':
        return [
          {
            key: 'delete',
            label: 'Delete',
            icon: IconTrash,
            danger: true,
            onSelect: () => {
              setDeleteProblem(null)
              setAsking(true)
            },
          },
        ]
    }
  })

  const message: ToastMessage | null = said ? { id: said.id, text: said.text } : null
  return (
    <>
      <BackToList />
      <div className={styles['head']}>
        <div>
          <p className={styles['kind']}>Workflow</p>
          <h1 tabIndex={-1}>{useCase.name}</h1>
        </div>
        <StatusPills state={useCase.state} fact={useCase.last_run ? pillOf(useCase.last_run) : null} test={useCase.last_run?.test === true} large />
      </div>
      <p className={styles['sentence']}>{sentenceOf(useCase)}</p>
      {leftOutWords(useCase.left_out) ? <p className={styles['leftOut']}>{leftOutWords(useCase.left_out)}</p> : null}
      {viewer.operator ? null : (
        <p className={styles['opsNote']}>
          <OperatorsNote what="this workflow" />
        </p>
      )}
      <StatusBanner banner={banner} resuming={move.isPending} onResume={() => pauseOrResume('resume')} />
      {runNow.error ? (
        <p className={styles['problem']} role="alert">
          {words(runNow.error)}
        </p>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <RunLine stations={templateLine(useCase)} arrivedLive={null} settled={null} />
      <div className={styles['pair']}>
        <When useCase={useCase} now={now} mayChange={mayChangeSchedule(useCase, viewer)} onSaved={(text) => setSaid((before) => ({ id: (before?.id ?? 0) + 1, text }))} />
        {gate ? (
          <section className={styles['section']} aria-labelledby="who-says-yes">
            <h2 id="who-says-yes">Who says yes</h2>
            <p>{whoSaysYes(useCase.owner, viewer, nameOf)}</p>
            <details className={styles['rule']}>
              <summary>Who can’t say yes</summary>
              <p>{ownWorkRule(useCase.schedule)}</p>
            </details>
          </section>
        ) : null}
      </div>
      {runs.data ? (
        <RecentRuns runs={recent} now={now} nameOf={nameOf} firstRun={useCase.next_run_at && !paused ? nextRunWords(useCase, now) : null} />
      ) : (
        <section className={styles['section']}>
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
      <Versions useCase={useCase} now={now} nameOf={nameOf} />
      <DraftActions useCase={useCase} viewer={viewer} />
      {mayPause || items.length > 0 ? (
        <div className={styles['actions']}>
          {mayPause ? (
            <Button icon={IconPause} data-place={placeOf('pause')} loading={move.isPending} onClick={() => pauseOrResume('pause')}>
              Pause
            </Button>
          ) : null}
          {items.length > 0 ? <ActionMenu items={items} buttonRef={moreButton} busy={runNow.pending} place={placeOf('run')} /> : null}
        </div>
      ) : null}
      {asking ? (
        <DeleteDialog
          name={useCase.name}
          pastRuns={runs.data ? recent.length : null}
          busy={removal.isPending}
          problem={deleteProblem}
          onClose={() => {
            setAsking(false)
            moreButton.current?.focus()
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
  const useCase = useUseCase(useCaseId, true, { poll: REFRESH_MS })
  const me = useMe()
  const shown = useCase.data && me.data && !useCase.isError ? controlsOf(useCase.data, viewerOf(me.data)).map(placeOf) : []
  const refocus = useFocusAfterReread(PLACES_IN_PAGE_ORDER, shown, Math.max(useCase.dataUpdatedAt, useCase.errorUpdatedAt))
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
  return <WorkflowView useCase={useCase.data} me={me.data} now={now} onReread={refocus} />
}

export function WorkflowRoute({ now }: { now: Date }) {
  const { useCaseId = '' } = useParams()
  return <WorkflowLoader key={useCaseId} useCaseId={useCaseId} now={now} />
}
