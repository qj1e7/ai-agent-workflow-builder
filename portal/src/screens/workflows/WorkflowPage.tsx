import { useEffect, useId, useRef, useState, type MouseEvent } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useStartRun, useUseCase, useWatchlist } from '../../api/queries'
import type { Me, UseCaseView } from '../../api/types'
import { useAddTheYesBack, useDeleteWorkflow, useMoveWorkflow, useRereadWorkflow, useRollback, useSaveWorkflowSchedule, useSweepOnFocus, useUseCaseInN8n } from '../../api/workflowQueries'
import { OperatorsNote } from '../../shell/OperatorsNote'
import { PageHead } from '../../shell/PageHead'
import { ActionMenu, type MenuItem } from '../../ui/ActionMenu'
import { Button, ButtonLink } from '../../ui/Button'
import { changePath } from '../home/edit'
import { useFocusAfterReread } from '../../ui/focus'
import { useFromChat } from '../../ui/fromChat'
import { openedFromList } from '../../ui/fromList'
import { IconChevronLeft, IconPause, IconPlay, IconTrash } from '../../ui/icons'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { useView, ViewTabs } from '../../ui/ViewTabs'
import { RunLine } from '../run/RunLine'
import { SoftwareRoute } from '../software/SoftwarePage'
import { bannerRepeatsThePage, leadsThePage, StatusBanner, titleRowAction } from './Banner'
import { useArrivalScroll } from './arrival'
import { templateLine } from './line'
import { RecentRuns } from './RecentRuns'
import { backToVersionToast, yesBackToast } from './n8nChange'
import { StatusPills } from './Status'
import { Versions } from './Versions'
import { useDraft } from './DraftActions'
import { UseCaseSimulation } from './UseCaseSimulation'
import { HeldInN8n, OpenInN8nEditor, WorkflowInN8n } from './InN8n'
import { cantChangeWords, heldOf, holdOf, mayOpen, openingOf } from './n8nHold'
import { NextRun, When } from './When'
import {
  APPROVAL_RULE,
  bannerOf,
  changeProblem,
  changeWords,
  controlsOf,
  isWatchlist,
  deleteWords,
  leftOutWords,
  mainActionOf,
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
  runsOf,
  scheduleSavedWords,
  sentenceOf,
  viewerOf,
  whoSaysYes,
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
  const rollback = useRollback()
  const addYes = useAddTheYesBack()
  const saveAgain = useSaveWorkflowSchedule(id)
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
  const n8nAccess = me.n8n_access === true
  const [view, showView] = useView()
  const shownView = n8nAccess ? view : 'main'
  const inN8n = useUseCaseInN8n(id, { enabled: n8nAccess, poll: REFRESH_MS })
  const held = heldOf(useCase, me, n8nAccess ? openingOf(inN8n) : null)
  const hold = n8nAccess && inN8n.data ? holdOf(inN8n.data, useCase, me) : null
  const openable = hold !== null && mayOpen(hold) ? hold : null
  useArrivalScroll()
  useSweepOnFocus(viewer.operator, id)

  const recent = runsOf(runs.data ?? [], id)
  const paused = useCase.state === 'paused'
  const controls = controlsOf(useCase, viewer)
  const menuActions = menuActionsOf(useCase, viewer)
  // The watchlist's Run now checks its list, so it waits for software to check, and is never drawn dead.
  const watching = useWatchlist({ enabled: isWatchlist(useCase) })
  const nothingToCheck = isWatchlist(useCase) && (watching.data?.software.length ?? 0) === 0
  const runNowLeads = mainActionOf(useCase, viewer) === 'run' && !nothingToCheck
  const mayPause = controls.includes('pause')
  // The chat's edit card changes when it runs, the one thing the platform changes in a saved workflow. The watchlist and one made in n8n have their own places for it.
  const mayChange = mayChangeSchedule(useCase, viewer) && held === null
  const banner = bannerOf({ useCase, viewer, now, nameOf })
  const gate = useCase.plan.some((block) => block.kind === 'approval')
  const draft = useDraft(useCase, viewer)
  const showBanner = !bannerRepeatsThePage(banner, useCase)
  const runAction = banner.action !== null && titleRowAction(banner.action) ? banner.action : null

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

  function republish(action: Extract<NonNullable<typeof banner.action>, { kind: 'yes' | 'undo' | 'resave' }>) {
    const answers = (toast: (view: UseCaseView) => string) => ({
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        setSaid((before) => ({ id: (before?.id ?? 0) + 1, text: toast(view) }))
      },
      onError: (error: unknown) => {
        rereadIfOutOfDate('switch')(error)
        setProblem(words(error))
      },
    })
    const send = { useCaseId: id, inUse: useCase.version, via: 'page' } as const
    if (action.kind === 'yes') addYes.mutate(send, answers((view) => yesBackToast(view.version)))
    else if (action.kind === 'resave') saveAgain.mutate({ day: action.day, at: action.at, expected_version: useCase.version }, answers((view) => scheduleSavedWords(view, now)))
    else rollback.mutate({ ...send, version: action.to }, answers((view) => backToVersionToast(action.to, view.version)))
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

  const say = (text: string) => setSaid((before) => ({ id: (before?.id ?? 0) + 1, text }))
  // The Software watchlist is a workflow like the rest. Its list, and each software's page, are drawn inside it.
  const listed = isWatchlist(useCase)
  const software = useSearchParams()[0].get('software')
  if (listed && software !== null && shownView === 'main') return <SoftwareRoute now={now} rowId={software} held={held !== null} />
  const message: ToastMessage | null = said ? { id: said.id, text: said.text } : null
  return (
    <>
      <BackToList />
      <div className={styles['head']}>
        <div className={styles['titleBlock']}>
          <p className={styles['kind']}>Workflow</p>
          <div className={styles['titleLine']}>
            <h1 tabIndex={-1}>{useCase.name}</h1>
            <StatusPills useCase={useCase} large />
          </div>
        </div>
        {shownView === 'main' ? (
          <div className={styles['titleActions']}>
            {runAction?.kind === 'resume' ? (
              <Button variant="primary" icon={IconPlay} data-place="switch" loading={move.isPending} onClick={() => pauseOrResume('resume')}>
                Resume
              </Button>
            ) : runAction ? (
              <ButtonLink to={`/runs/${runAction.runId}`} variant={leadsThePage(runAction) ? 'primary' : 'secondary'}>
                {runAction.kind === 'decide' ? 'Review and decide' : 'Open the run'}
              </ButtonLink>
            ) : null}
            {draft?.buttons}
            {runNowLeads ? (
              <Button variant={listed || leadsThePage(banner.action) ? 'secondary' : 'primary'} icon={IconPlay} data-place={placeOf('run')} loading={runNow.pending} onClick={runNow.press}>
                Run now
              </Button>
            ) : null}
            {mayPause ? (
              <Button icon={IconPause} data-place={placeOf('pause')} loading={move.isPending} onClick={() => pauseOrResume('pause')}>
                Pause
              </Button>
            ) : null}
            {mayChange ? <ButtonLink to={changePath(id)}>Change</ButtonLink> : null}
            {openable ? <OpenInN8nEditor useCaseId={id} hold={openable} variant="secondary" /> : null}
            {items.length > 0 ? <ActionMenu items={items} buttonRef={moreButton} busy={!runNowLeads && runNow.pending} place={placeOf('delete')} /> : null}
          </div>
        ) : null}
      </div>
      {n8nAccess ? <ViewTabs main="Summary" shown={shownView} onShow={showView} className={styles['views']} /> : null}
      {shownView === 'n8n' ? (
        <WorkflowInN8n useCase={useCase} inN8n={inN8n} me={me} now={now} say={say} />
      ) : (
        <>
          <p className={styles['sentence']}>{sentenceOf(useCase)}</p>
          {leftOutWords(useCase.left_out) ? <p className={styles['leftOut']}>{leftOutWords(useCase.left_out)}</p> : null}
          {viewer.operator ? null : (
            <p className={styles['opsNote']}>
              <OperatorsNote what="this workflow" />
            </p>
          )}
          {held ? <HeldInN8n useCaseId={id} hold={held} now={now} say={say} /> : null}
          {draft ? <p className={`muted ${styles['draftWords'] ?? ''}`}>{draft.words}</p> : null}
          {showBanner ? <StatusBanner banner={banner} resuming={move.isPending} onResume={() => pauseOrResume('resume')} onRepublish={republish} republishing={rollback.isPending || addYes.isPending || saveAgain.isPending} /> : null}
          {useCase.moving_to_n8n ? (
            <p className="muted" role="status">
              Moving to n8n after this run.
            </p>
          ) : null}
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
          {draft?.problem}
          <div className={styles['strip']}>
            {listed ? null : <When useCase={useCase} now={now} mayChange={mayChangeSchedule(useCase, viewer)} held={held ? cantChangeWords(held) : null} onSaved={say} />}
            {gate ? (
              <section className={styles['section']} aria-labelledby="who-approves">
                <h2 id="who-approves">Who approves</h2>
                <p>{whoSaysYes(useCase.owner, viewer, nameOf)}</p>
                <p>{APPROVAL_RULE}</p>
                <details className={styles['rule']}>
                  <summary>Who can’t approve</summary>
                  <p>{ownWorkRule(useCase.schedule)}</p>
                </details>
              </section>
            ) : null}
            {listed ? null : <NextRun useCase={useCase} now={now} />}
          </div>
          <RunLine stations={templateLine(useCase)} arrivedLive={null} settled={null} />
          {listed ? <SoftwareRoute now={now} rowId={null} held={held !== null} /> : null}
          <div className={useCase.version >= 2 ? styles['duo'] : undefined}>
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
            {useCase.version >= 2 ? <Versions useCase={useCase} now={now} nameOf={nameOf} operator={viewer.operator} say={say} /> : null}
          </div>
          {useCase.state === 'draft' ? <UseCaseSimulation useCaseId={id} /> : null}
        </>
      )}
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
  return <WorkflowView useCase={useCase.data} me={me.data} now={now} onReread={refocus} />
}

export function WorkflowRoute({ now }: { now: Date }) {
  const { useCaseId = '' } = useParams()
  return <WorkflowLoader key={useCaseId} useCaseId={useCaseId} now={now} />
}
