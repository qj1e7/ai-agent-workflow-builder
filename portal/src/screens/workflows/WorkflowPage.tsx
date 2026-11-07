import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useStartRun, useUseCase } from '../../api/queries'
import type { Me, UseCaseView } from '../../api/types'
import { useDeleteWorkflow, useMoveWorkflow, useRereadWorkflow, useSaveWorkflowSchedule } from '../../api/workflowQueries'
import { stoppedActions } from '../home/home'
import { RetryButton } from '../home/HomeItem'
import { PageHead } from '../../shell/PageHead'
import { AgentFace } from '../../ui/AgentFace'
import { ActionMenu, type MenuItem } from '../../ui/ActionMenu'
import { Button, ButtonLink } from '../../ui/Button'
import { useFocusAfterReread } from '../../ui/focus'
import { FROM_LIST, openedFromList } from '../../ui/fromList'
import { IconAlert, IconCheck, IconChevronLeft, IconLock, IconPause, IconPencil, IconPlay, IconTrash, type Icon } from '../../ui/icons'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { ScheduleForm, useEditorThatRefocusesItsOpener, type SaveSchedule } from '../software/Schedule'
import { useArrivalScroll } from './arrival'
import { RecentRuns } from './RecentRuns'
import { StatusPills, useChanges } from './Status'
import {
  agentsOf,
  bannerOf,
  changeProblem,
  changeWords,
  controlsOf,
  deleteWords,
  heldNote,
  mayChangeSchedule,
  menuActionsOf,
  nextRunWords,
  placeOf,
  PLACES_IN_PAGE_ORDER,
  pressChange,
  pressRunNow,
  REFRESH_MS,
  rereadWhenOutOfDate,
  runFact,
  runsOf,
  scheduleSaver,
  SOFTWARE_PAGE,
  stepTag,
  viewerOf,
  whenWords,
  workflowPath,
  type Banner,
  type Place,
} from './workflow'
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

function Schedule({ useCase, now, change }: { useCase: UseCaseView; now: Date; change: ReactNode }) {
  const { words, small } = whenWords(useCase)
  const next = heldNote(useCase) ?? nextRunWords(useCase, now)
  const changes = useChanges(next)
  return (
    <div>
      <dt>Schedule</dt>
      <dd>
        {words}
        <small>{small}</small>
        {useCase.schedule ? <small>Set by {useCase.schedule.owner_name}.</small> : null}
        <small>
          <span key={changes} className={changes > 0 ? styles['changed'] : undefined}>
            Next run: {next}
          </span>
        </small>
      </dd>
      {change ? <dd className={styles['rowAction']}>{change}</dd> : null}
    </div>
  )
}

interface PanelProps {
  readonly useCase: UseCaseView
  readonly now: Date
  readonly onSaved: (words: string) => void
  readonly onDone: () => void
}

/** The prototype's "Change schedule" panel under the facts. Saving makes the Operator the schedule owner, and a stale save reads the workflow again. */
export function ScheduleChangePanel({ useCase, now, onSaved, onDone }: PanelProps) {
  const id = useCase.use_case_id
  const headingId = useId()
  const save = useSaveWorkflowSchedule(id)
  const reread = useRereadWorkflow()
  const saveAndSay: SaveSchedule = {
    isPending: save.isPending,
    mutate: scheduleSaver((body, answers) => save.mutate(body, answers), { useCaseId: id, now, say: onSaved, refocus: () => undefined, reread }),
  }
  return (
    <section className={`${styles['panel']} ${styles['change']}`} aria-labelledby={headingId}>
      <h2 id={headingId}>Change schedule</h2>
      <ScheduleForm schedule={useCase.schedule} work="runs" save={saveAndSay} onDone={onDone} />
    </section>
  )
}

function Steps({ useCase }: { useCase: UseCaseView }) {
  return (
    <section>
      <h3>What it does</h3>
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

function Technical({ useCase, paused }: { useCase: UseCaseView; paused: boolean }) {
  return (
    <details className={styles['tech']}>
      <summary>Technical details</summary>
      <div className={styles['techBody']}>
        <Steps useCase={useCase} />
        <section>
          <h3>Agents</h3>
          <span className={styles['chips']}>
            {agentsOf(useCase).map((agent) => (
              <Link key={agent.to} to={agent.to} state={FROM_LIST} className={styles['chip']}>
                <AgentFace id={agent.face} display={agent.name} size={28} state={paused ? 'stopped' : 'idle'} />
                {agent.name}
              </Link>
            ))}
          </span>
        </section>
      </div>
    </details>
  )
}

const BANNER_ICON: Record<Banner['tone'], Icon | null> = { ok: IconCheck, wait: IconLock, bad: IconAlert, off: IconPause, new: null }

interface BannerViewProps {
  readonly banner: Banner
  readonly resuming: boolean
  readonly onResume: () => void
}

interface ButtonProps {
  readonly action: NonNullable<Banner['action']>
  readonly resuming: boolean
  readonly onResume: () => void
  readonly describedBy: string
}

function BannerButton({ action, resuming, onResume, describedBy }: ButtonProps) {
  switch (action.kind) {
    case 'resume':
      return (
        <Button variant="primary" icon={IconPlay} data-place="switch" loading={resuming} onClick={onResume}>
          Resume
        </Button>
      )
    case 'decide':
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant="primary">
          Review and decide
        </ButtonLink>
      )
    case 'stopped': {
      const [first] = stoppedActions(action.runId, action.retryable)
      if (first?.kind === 'retry') return <RetryButton runId={first.runId} label={first.label} primary describedBy={describedBy} />
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant="primary">
          {first?.kind === 'open' ? first.label : 'See why it stopped'}
        </ButtonLink>
      )
    }
  }
}

/** One sentence on the state and the one action that moves it on. The tone is also in the words, never in colour alone. */
function StatusBanner({ banner, resuming, onResume }: BannerViewProps) {
  const Mark = BANNER_ICON[banner.tone]
  const { action } = banner
  const textId = useId()
  return (
    <div className={styles['banner']} data-tone={banner.tone}>
      <span className={styles['bannerMark']}>{Mark ? <Mark size={20} /> : null}</span>
      <p id={textId}>{banner.text}</p>
      {action ? <BannerButton action={action} resuming={resuming} onResume={onResume} describedBy={textId} /> : null}
    </div>
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
  const { editing: changingSchedule, opener: scheduleOpener, open: openSchedule, close: closeSchedule } = useEditorThatRefocusesItsOpener()
  const scheduleFromMenu = useRef(false)
  const [asking, setAsking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [deleteProblem, setDeleteProblem] = useState<string | null>(null)
  const [said, setSaid] = useState<Said | null>(null)
  const switchedTo = useRef<UseCaseView['state'] | null>(null)
  useArrivalScroll()

  // A form the menu opened hands focus back to the menu button. The hook that closed it has already focused the form's own opener, so this runs after it.
  useEffect(() => {
    if (changingSchedule || !scheduleFromMenu.current) return
    scheduleFromMenu.current = false
    moreButton.current?.focus()
  }, [changingSchedule])

  const recent = runsOf(runs.data ?? [], id)
  const latest = recent[0] ?? null
  const fact = latest ? runFact(latest, nameOf) : null
  const paused = useCase.state === 'paused'
  const controls = controlsOf(useCase, viewer)
  const menuActions = menuActionsOf(useCase, viewer)
  const mayPause = controls.includes('pause')
  const banner = bannerOf({ useCase, latest, viewer, now, nameOf })

  // The control that took the press leaves the page, so focus follows to its replacement: Resume in the banner, or Pause in the header.
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

  const items: MenuItem[] = menuActions.map((action): MenuItem => {
    switch (action) {
      case 'run':
        return { key: 'run', label: 'Run now', icon: IconPlay, onSelect: runNow.press }
      case 'schedule':
        return { key: 'schedule', label: useCase.schedule ? 'Change schedule' : 'Set a schedule', icon: IconPencil, onSelect: () => {
            scheduleFromMenu.current = true
            openSchedule()
          },
        }
      case 'delete':
        return {
          key: 'delete',
          label: 'Delete',
          icon: IconTrash,
          danger: true,
          onSelect: () => {
            setDeleteProblem(null)
            setAsking(true)
          },
        }
    }
  })

  const message: ToastMessage | null = said ? { id: said.id, text: said.text } : null
  const changeSchedule =
    mayChangeSchedule(useCase, viewer) && !changingSchedule ? (
      <Button
        ref={scheduleOpener}
        data-place="schedule"
        onClick={() => {
          scheduleFromMenu.current = false
          openSchedule()
        }}
      >
        {useCase.schedule ? 'Change' : 'Set'}
        <span className="visually-hidden"> schedule</span>
      </Button>
    ) : null
  return (
    <>
      <BackToList />
      <div className={styles['head']}>
        <div>
          <StatusPills state={useCase.state} fact={fact} />
          <h1 tabIndex={-1}>{useCase.name}</h1>
          <p>{useCase.instruction}</p>
        </div>
        {mayPause || items.length > 0 ? (
          <div className={styles['btns']}>
            {mayPause ? (
              <Button icon={IconPause} data-place={placeOf('pause')} loading={move.isPending} onClick={() => pauseOrResume('pause')}>
                Pause
              </Button>
            ) : null}
            {items.length > 0 ? <ActionMenu items={items} buttonRef={moreButton} busy={runNow.pending} place={placeOf('run')} /> : null}
          </div>
        ) : null}
      </div>
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
      <dl className={styles['factrows']}>
        <Schedule useCase={useCase} now={now} change={changeSchedule} />
        <div>
          <dt>Approval</dt>
          <dd>
            {WHO_APPROVES}
            <small>Owned by {nameOf(useCase.owner)}.</small>
          </dd>
        </div>
      </dl>
      {changingSchedule && mayChangeSchedule(useCase, viewer) ? (
        <ScheduleChangePanel useCase={useCase} now={now} onSaved={(text) => setSaid((before) => ({ id: (before?.id ?? 0) + 1, text }))} onDone={closeSchedule} />
      ) : null}
      <div className={styles['stack']}>
        {runs.data ? (
          <RecentRuns runs={recent} now={now} nameOf={nameOf} firstRun={useCase.next_run_at && !paused ? nextRunWords(useCase, now) : null} />
        ) : (
          <section className={styles['panel']}>
            <h2>Recent activity</h2>
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
        <Technical useCase={useCase} paused={paused} />
      </div>
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
  const useCase = useUseCase(useCaseId)
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
