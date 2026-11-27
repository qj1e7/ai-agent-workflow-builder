import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { useApproval, useRun, useUseCase } from '../../api/queries'
import { useNow } from '../../api/ticking'
import type { RunView, UseCaseView } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { PRODUCT } from '../../shell/product'
import { AgentFace, type FaceState } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { useFromChat } from '../../ui/fromChat'
import { useView, ViewTabs } from '../../ui/ViewTabs'
import { motionAllowed } from '../../ui/motion'
import { nextRunOf } from '../workflows/workflow'
import { DECISION_ID, DecisionArea } from './Chat'
import { FixSection, useFixLeads } from './FixPanel'
import { foundLine, runByWords, statusOf, tenseOf, workingLine } from './happened'
import { History } from './History'
import { RunInN8n } from './InN8n'
import { partyOf, useDecision } from './decision'
import { POLL_FAILED_MS, useReconnectWhenBehind } from './follow'
import { useLiveRun, type LiveRun } from './liveRun'
import { Outcome, StopAnswers, StopNext } from './Outcome'
import { useQuestions } from './questions'
import { RunDecision } from './RunDecision'
import { RunLine } from './RunLine'
import { RunPill } from './RunPill'
import { RunPlaceContext, type RunPlace } from './place'
import { isFinished, type RunModel } from './runModel'
import { troubleFaceOf } from './troubleFace'
import { IconChevronLeft } from '../../ui/icons'
import { historyOpen } from './historyOpen'
import { landingOf, scrollsToDecision } from './landing'
import { useRunStory } from './useRunStory'
import { testAgainOf } from './testAgain'
import { announcementOf, declinedNext, declinedNowWords, feedTroubleOf, logRowsOf, messageRowsOf, RUN_MISSING, RUN_PROBLEM, stageWords } from './words'
import styles from './RunPage.module.css'

function notFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

function Loading() {
  return (
    <p className="muted" role="status">
      Loading the run
    </p>
  )
}

function Stopped({ heading, lead }: { heading: string; lead: string }) {
  return (
    <>
      <PageHead heading={heading} lead={lead} />
      <p>
        <Link to="/">Go to Home</Link>
      </p>
    </>
  )
}

function Missing({ what }: { what: 'run' | 'approval' }) {
  return what === 'run' ? <Stopped {...RUN_MISSING} /> : <Stopped heading="Approval not found" lead="There is no approval at this address." />
}

function Problem({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <PageHead {...RUN_PROBLEM} />
      <Button onClick={onRetry}>Try again</Button>
    </>
  )
}

function FeedNotReady({ connection, onRetry }: { connection: LiveRun['connection']; onRetry: () => void }) {
  const { kind } = useSession()
  const trouble = feedTroubleOf(connection, kind)
  switch (trouble.kind) {
    case 'loading':
      return <Loading />
    case 'waiting':
      return (
        <p className="muted" role="status">
          {trouble.words}
        </p>
      )
    case 'stop':
      return <Stopped heading={trouble.heading} lead={trouble.lead} />
    case 'retry':
      return <Problem onRetry={onRetry} />
  }
}

export function RunRoute() {
  const { runId = '' } = useParams()
  return <RunPage key={runId} runId={runId} fromApproval={false} />
}

export function ApprovalRoute() {
  const { approvalId = '' } = useParams()
  const approval = useApproval(approvalId)
  if (approval.isPending) return <Loading />
  if (approval.isError) return notFound(approval.error) ? <Missing what="approval" /> : <Problem onRetry={() => void approval.refetch()} />
  return <RunPage key={approval.data.run_id} runId={approval.data.run_id} fromApproval />
}

function RunPage({ runId, fromApproval }: { runId: string; fromApproval: boolean }) {
  const run = useRun(runId)
  if (run.isError) return notFound(run.error) ? <Missing what="run" /> : <Problem onRetry={() => void run.refetch()} />
  if (!run.data) return <Loading />
  return <LiveRunPage run={run.data} fromApproval={fromApproval} />
}

function LiveRunPage({ run, fromApproval }: { run: RunView; fromApproval: boolean }) {
  const { live, restart, tryAgain } = useLiveRun(run.run_id)
  const failed = live.head.phase.state === 'failed'
  const latest = useRun(run.run_id, { poll: failed ? POLL_FAILED_MS : false }).data ?? run
  const useCase = useUseCase(run.use_case_id)
  const [detail, setDetail] = useState<boolean | null>(null)
  useReconnectWhenBehind(failed && live.loaded && latest.last_seq > live.head.seq, restart)

  const ready = live.loaded || live.connection.is === 'live' || live.connection.is === 'settled'
  if (!ready) return <FeedNotReady connection={live.connection} onRetry={tryAgain} />
  if (useCase.isLoading) return <Loading />
  return <RunView run={latest} useCase={useCase.data} live={live} fromApproval={fromApproval} detail={{ choice: detail, choose: setDetail }} />
}

function backTo(useCase: UseCaseView | undefined): string {
  return useCase?.template === 'software_watchlist' ? `/workflows/${useCase.use_case_id}` : '/workflows'
}

function useFollowUntilScrolled(newest: number, loadedUpTo: number, list: RefObject<HTMLOListElement | null>): void {
  const following = useRef(true)
  useEffect(() => {
    const stop = () => {
      following.current = false
    }
    const keys = (event: KeyboardEvent) => {
      if (['PageDown', 'PageUp', 'ArrowDown', 'ArrowUp', 'Home', 'End', ' '].includes(event.key)) stop()
    }
    window.addEventListener('wheel', stop, { passive: true })
    window.addEventListener('touchmove', stop, { passive: true })
    window.addEventListener('keydown', keys)
    return () => {
      window.removeEventListener('wheel', stop)
      window.removeEventListener('touchmove', stop)
      window.removeEventListener('keydown', keys)
    }
  }, [])
  useEffect(() => {
    if (!following.current || newest <= loadedUpTo) return
    list.current?.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: motionAllowed() ? 'smooth' : 'auto' })
  }, [newest, loadedUpTo, list])
}

interface RunViewProps {
  readonly run: RunView
  readonly useCase: UseCaseView | undefined
  readonly live: LiveRun
  readonly fromApproval: boolean
  /** Whether a long Step by step is open, once the person chose. Null follows the run. */
  readonly detail: { readonly choice: boolean | null; readonly choose: (open: boolean) => void }
}

const WORKING = new Set<RunModel['phase']['state']>(['pending', 'working', 'proposed', 'acting'])

/** The troubleshooter's face beside its words, as the sketch's `tr big`. Its mood follows the run, and a fix while one runs. */
function TroubleshooterBlock({ face, children }: { face: FaceState; children: ReactNode }) {
  return (
    <div className={styles['trouble']}>
      <AgentFace id="troubleshooter" size={34} state={face} />
      <div className={styles['troubleBody']}>{children}</div>
    </div>
  )
}

function RunView({ run, useCase, live, fromApproval, detail }: RunViewProps) {
  const { shown, loadedUpTo } = live
  const story = useRunStory(run, live)
  const { me, nameOf, approval, facts, stations, arrivedLive } = story
  const fromChat = useFromChat()
  const [lands] = useState(() => landingOf(shown.phase.state, fromApproval))
  const logList = useRef<HTMLOListElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const n8nAccess = me?.n8n_access === true
  const [view, showView] = useView()
  /** Redrawn each minute, so a fix whose twenty minutes run out stops showing as at work. */
  const now = useNow(() => new Date()).getTime()
  const shownView = n8nAccess ? view : 'main'
  const fixAsk = {
    runId: run.run_id,
    operator: story.stopped.me?.operator === true,
    next: story.stopped.advice?.answers.next,
    offer: run.state === 'failed' ? run.fix_offer : undefined,
    now,
    approverId: me?.roles.includes('approver') ? me.id : null,
  }
  const fixLeading = useFixLeads({ ...fixAsk, fix: shown.fix })

  const waiting = shown.phase.state === 'awaiting_approval'
  const saidByMe = me ? shown.chat.findLast((item) => item.kind === 'decided' && item.by === me.id) : undefined
  const [said, setSaid] = useState<ToastMessage | null>(null)
  const say = (text: string) => setSaid((before) => ({ id: (before?.id ?? 0) + 1, text }))
  const place: RunPlace = { focus: () => heading.current?.focus(), say }
  const decision = useDecision(approval, partyOf(approval, me?.id), (recorded) => {
    if (recorded.verdict === 'decline') say(declinedNowWords({ reason: recorded.reason ?? null }))
  })
  const questions = useQuestions(approval, nameOf, say)
  const rows = logRowsOf(shown.chat, nameOf, story.quick)
  const messages = messageRowsOf(shown.chat)
  const open = historyOpen(detail.choice, shown)
  const answered = decision.recorded !== null && !waiting && !WORKING.has(shown.phase.state)
  const focused = useRef(false)
  useEffect(() => {
    if (!answered || focused.current) return
    focused.current = true
    const line = logList.current?.querySelector<HTMLElement>(`[data-gate-said="${saidByMe?.seq ?? ''}"]`)
    ;(open ? line : document.getElementById(DECISION_ID))?.focus({ preventScroll: true })
  })

  const newest = shown.chat.at(-1)
  const next = declinedNext({ test: run.test, watchlist: useCase?.template === 'software_watchlist' }, nextRunOf(useCase), new Date())
  const announce = newest && newest.seq > loadedUpTo ? announcementOf(newest, nameOf, next) : null
  const status = statusOf(facts, nameOf)

  const title = `${run.use_case_name}: ${status.label}`
  useEffect(() => {
    document.title = `${title} · ${PRODUCT}`
  }, [title])

  useEffect(() => {
    if (lands === null) return
    const decisionArea = document.getElementById(DECISION_ID)
    if (!decisionArea) {
      document.querySelector<HTMLElement>('main h1')?.focus({ preventScroll: true })
      return
    }
    decisionArea.focus({ preventScroll: true })
    if (scrollsToDecision(lands, decisionArea.getBoundingClientRect(), window.innerHeight)) decisionArea.scrollIntoView({ block: 'start' })
  }, [lands])

  useFollowUntilScrolled(newest?.seq ?? 0, loadedUpTo, logList)

  const modelFinished = isFinished(shown.phase)
  const found = foundLine(shown.release, run.use_case_name, useCase?.template, new Date())
  const failure = shown.phase.state === 'failed' ? shown.phase : null
  const safeId = `${run.run_id}-safe`
  const troubleFace = troubleFaceOf(facts.state, shown.fix, now)
  const tense = tenseOf(shown.phase.state)
  const requested = story.approvalId !== null && tense !== undefined
  const main = failure ? (
    <DecisionArea label="Why it stopped">
      <TroubleshooterBlock face={troubleFace}>
        <StopAnswers failure={failure} {...story.stopped} safeId={safeId} />
        <RunPlaceContext.Provider value={place}>
          <div className={styles['stopActions']}>
            <StopNext runId={run.run_id} failure={failure} {...story.stopped} quiet={fixLeading} safeId={safeId} />
          </div>
        </RunPlaceContext.Provider>
        <FixSection {...fixAsk} fix={shown.fix} loadedUpTo={loadedUpTo} />
      </TroubleshooterBlock>
    </DecisionArea>
  ) : requested ? (
    <DecisionArea label="Approval">
      {approval ? (
        <RunDecision
          approval={approval}
          found={found}
          tense={tense}
          decision={decision}
          facts={facts}
          reasons={story.quick}
          requester={nameOf(approval.requester)}
          questions={questions}
          me={me?.id}
          party={partyOf(approval, me?.id)}
          nameOf={nameOf}
          next={null}
          now={new Date()}
        />
      ) : (
        <p className="muted" role="status">
          Loading the approval
        </p>
      )}
      {shown.phase.state === 'rejected' ? <Outcome declinedNext={next} testAgain={testAgainOf({ ...run, state: shown.phase.state }, me, story.stopped.modelOff ?? false)} /> : null}
    </DecisionArea>
  ) : (
    <DecisionArea label="Run">
      {found ? <p className={styles['found']}>{found}</p> : null}
      <p>{modelFinished ? stageWords(facts, nameOf) : workingLine(facts)}</p>
    </DecisionArea>
  )

  return (
    <div className={styles['page']}>
      {fromChat ? null : (
        <Link to={backTo(useCase)} className={styles['back']}>
          <IconChevronLeft size={16} />
          {run.use_case_name}
        </Link>
      )}
      <div className={styles['head']}>
        <h1 ref={heading} tabIndex={-1} data-page-moves-focus={lands !== null || undefined}>
          {run.use_case_name}
        </h1>
        <span className={styles['by']}>{runByWords(shown.trigger, shown.startedBy, nameOf)}</span>
        <RunPill facts={facts} nameOf={nameOf} />
      </div>
      {n8nAccess ? <ViewTabs main="Steps" shown={shownView} onShow={showView} className={styles['views']} /> : null}
      <p className={styles['status']} role="status">
        {statusWords(live)}
      </p>
      {shownView === 'n8n' ? (
        <div className={styles['inN8n']}>
          <RunInN8n runId={run.run_id} name={run.use_case_name} seq={shown.seq} ended={modelFinished} />
        </div>
      ) : null}
      {main}
      {failure && shownView !== 'n8n' ? (
        <div className={styles['stoppedLine']}>
          <RunLine stations={stations} arrivedLive={arrivedLive} settled={null} />
        </div>
      ) : null}
      <History
        rows={rows}
        messages={messages}
        loadedUpTo={loadedUpTo}
        open={open}
        onToggle={detail.choose}
        listRef={logList}
        line={shownView === 'n8n' || failure ? null : <RunLine stations={stations} arrivedLive={arrivedLive} settled={null} />}
      />
      <div className="visually-hidden" aria-live="polite">
        {announce ?? ''}
      </div>
      <Toast message={said} onDismiss={() => setSaid(null)} />
    </div>
  )
}

/** The page's status line: only what the live connection says, since the record and the status already say what was decided. */
export function statusWords(live: LiveRun): string {
  if (live.connection.is === 'reconnecting') return 'Lost the live connection. Trying again.'
  if (live.connection.is === 'closed') return 'Stopped following this run. Reload the page to see what changed.'
  return ''
}
