import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { useApproval, useRun, useUseCase } from '../../api/queries'
import type { RunView, UseCaseView } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { PRODUCT } from '../../shell/product'
import { AgentFace } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import { Toast, type ToastMessage } from '../../ui/Toast'
import { useFromChat } from '../../ui/fromChat'
import { motionAllowed } from '../../ui/motion'
import { nextRunOf } from '../workflows/workflow'
import { ApprovalGate, NotChecked } from './ApprovalGate'
import { DECISION_ID, DecisionArea, LONG_LOG, StepLog } from './Chat'
import { askedWords, foundOf, partyOf, useDecision, useNotChecked, yourPart, type Decision } from './decision'
import { POLL_FAILED_MS, useReconnectWhenBehind } from './follow'
import { useLiveRun, type LiveRun } from './liveRun'
import { AnswerList, Outcome, StopAnswers, StopNext } from './Outcome'
import { QuestionThread } from './QuestionThread'
import { useQuestions } from './questions'
import { RunLine } from './RunLine'
import { RunPill } from './RunPill'
import { isFinished, type RunModel } from './runModel'
import { TROUBLE_FACE } from './troubleFace'
import { useRunStory } from './useRunStory'
import { declinedNext, declinedNowWords, declinedRecord, feedTroubleOf, lineOf, logRowsOf, RUN_MISSING, RUN_PROBLEM, speakerName, stageWords, type NameOf, type RunState } from './words'
import styles from './RunPage.module.css'

const LANDS_ON_DECISION = new Set(['awaiting_approval', 'failed', 'rejected'])

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
  return useCase?.template === 'software_watchlist' ? '/software' : '/workflows'
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

/** A short log is always open. A long one is open while the agents work, and folded once the run needs the person or is over. */
function logOpen(choice: boolean | null, model: RunModel): boolean {
  return choice ?? WORKING.has(model.phase.state)
}

/** The troubleshooter's face beside its words, as the sketch's `tr big`. Its mood follows the run. */
function TroubleshooterBlock({ state, children }: { state: RunState; children: ReactNode }) {
  return (
    <div className={styles['trouble']}>
      <AgentFace id="troubleshooter" size={34} state={TROUBLE_FACE[state]} />
      <div className={styles['troubleBody']}>{children}</div>
    </div>
  )
}

function RunView({ run, useCase, live, fromApproval, detail }: RunViewProps) {
  const { shown, head, loadedUpTo } = live
  const story = useRunStory(run, live)
  const { me, nameOf, approval, facts, stations, settled, arrivedLive } = story
  const fromChat = useFromChat()
  const [lands] = useState(() => fromApproval || LANDS_ON_DECISION.has(shown.phase.state))
  const logList = useRef<HTMLOListElement>(null)

  const waiting = shown.phase.state === 'awaiting_approval'
  const saidByMe = me ? shown.chat.findLast((item) => item.kind === 'decided' && item.by === me.id) : undefined
  const [said, setSaid] = useState<ToastMessage | null>(null)
  const say = (text: string) => setSaid((before) => ({ id: (before?.id ?? 0) + 1, text }))
  const decision = useDecision(approval, partyOf(approval, me?.id), (recorded) => {
    if (recorded.verdict === 'decline') say(declinedNowWords({ reason: recorded.reason ?? null }))
  })
  const declinedSoFar = declinedSoFarWords(decision, live, nameOf)
  const questions = useQuestions(approval, nameOf, say)
  const notChecked = useNotChecked(approval, useCase)
  const rows = logRowsOf(shown.chat, nameOf, story.quick)
  const long = rows.length > LONG_LOG
  const open = !long || logOpen(detail.choice, shown)
  const answered = decision.recorded !== null && !waiting && !WORKING.has(shown.phase.state)
  const focused = useRef(false)
  useEffect(() => {
    if (!answered || focused.current) return
    focused.current = true
    const line = logList.current?.querySelector<HTMLElement>(`[data-gate-said="${saidByMe?.seq ?? ''}"]`)
    ;(open ? line : document.querySelector<HTMLElement>('main h1'))?.focus({ preventScroll: true })
  })

  const newest = shown.chat.at(-1)
  const next = declinedNext({ test: run.test, watchlist: useCase?.template === 'software_watchlist' }, nextRunOf(useCase), new Date())
  const announce = newest && newest.seq > loadedUpTo ? lineOf(newest, nameOf, next) : null

  const title = `${run.use_case_name}: ${stageWords(facts, nameOf)}`
  useEffect(() => {
    document.title = `${title} · ${PRODUCT}`
  }, [title])

  useEffect(() => {
    if (!lands) return
    const decisionArea = document.getElementById(DECISION_ID)
    if (!decisionArea) {
      document.querySelector<HTMLElement>('main h1')?.focus({ preventScroll: true })
      return
    }
    decisionArea.focus({ preventScroll: true })
    decisionArea.scrollIntoView({ block: 'start' })
  }, [lands])

  useFollowUntilScrolled(newest?.seq ?? 0, loadedUpTo, logList)

  const modelFinished = isFinished(shown.phase)
  const gate =
    waiting ? (
      <DecisionArea label="Approval">
        {approval && notChecked ? (
          <ApprovalGate
            approval={approval}
            page={{ found: foundOf(head.found, approval.found), part: yourPart(approval, partyOf(approval, me?.id), nameOf), askedBy: askedWords(approval, nameOf) }}
            decision={decision}
            notChecked={notChecked}
            reasons={story.quick}
            requester={nameOf(approval.requester)}
            questions={questions}
            me={me?.id}
            nameOf={nameOf}
          />
        ) : (
          <p className="muted" role="status">
            Loading what will be written
          </p>
        )}
      </DecisionArea>
    ) : null
  const failure = shown.phase.state === 'failed' ? shown.phase : null
  const safeId = `${run.run_id}-safe`
  const trouble =
    failure ? (
      <DecisionArea label="Why it stopped">
        <TroubleshooterBlock state={facts.state}>
          <StopAnswers failure={failure} {...story.stopped} safeId={safeId} />
        </TroubleshooterBlock>
      </DecisionArea>
    ) : story.answers.length > 0 && !waiting ? (
      <TroubleshooterBlock state={facts.state}>
        <AnswerList answers={story.answers} />
      </TroubleshooterBlock>
    ) : null
  const ending =
    modelFinished && shown.phase.state !== 'failed' ? (
      <DecisionArea label="How it ended">
        <Outcome
          declinedNext={shown.phase.state === 'rejected' ? next : null}
          record={
            approval ? (
              <>
                <NotChecked lines={notChecked ?? []} />
                <QuestionThread approval={approval} me={me?.id} nameOf={nameOf} answer={questions.answer} />
              </>
            ) : null
          }
        />
      </DecisionArea>
    ) : null

  return (
    <div className={styles['page']}>
      {fromChat ? null : (
        <Link to={backTo(useCase)} className={styles['back']}>
          <span aria-hidden="true">‹</span>
          {run.use_case_name}
        </Link>
      )}
      <div className={styles['head']}>
        <div>
          <p className={styles['kind']}>{story.kind}</p>
          <h1 tabIndex={-1} data-page-moves-focus={lands || undefined}>
            {run.use_case_name}
          </h1>
        </div>
        <RunPill facts={facts} />
      </div>
      <p className={styles['status']}>
        <span role="status">{statusWords(decision, live)}</span>
        {declinedSoFar ? ` ${declinedSoFar}` : null}
      </p>
      <RunLine stations={stations} arrivedLive={arrivedLive} settled={settled} />
      {trouble}
      {gate}
      {ending}
      <section className={styles['log']} aria-labelledby="step-by-step">
        <h2 id="step-by-step">Step by step</h2>
        {long ? (
          <details open={open}>
            <summary
              className={styles['detailToggle']}
              onClick={(event) => {
                event.preventDefault()
                detail.choose(!open)
              }}
            >
              {open ? 'Hide the steps' : `Show the ${rows.length} steps`}
            </summary>
            <StepLog ref={logList} rows={rows} loadedUpTo={loadedUpTo} />
          </details>
        ) : (
          <StepLog ref={logList} rows={rows} loadedUpTo={loadedUpTo} />
        )}
      </section>
      {failure ? (
        <div className={styles['foot']}>
          <StopNext runId={run.run_id} failure={failure} {...story.stopped} safeId={safeId} />
        </div>
      ) : null}
      <div className="visually-hidden" aria-live="polite">
        {announce ? `${speakerName(announce.speaker)}: ${announce.text}` : ''}
      </div>
      <Toast message={said} onDismiss={() => setSaid(null)} />
    </div>
  )
}

/** What the page says right after this person approved, before the run's own events catch up. */
export function statusWords(decision: Pick<Decision, 'recorded'>, live: LiveRun): string {
  if (live.connection.is === 'reconnecting') return 'Lost the live connection. Trying again.'
  if (live.connection.is === 'closed') return 'Stopped following this run. Reload the page to see what changed.'
  if (isFinished(live.shown.phase)) return ''
  if (decision.recorded === 'approve') return 'Approved. The platform is writing now.'
  return ''
}

/**
 * The decline this person just recorded, until the run's own events show it. Its message at the bottom of the page announces it,
 * so the line that keeps it is not live.
 */
export function declinedSoFarWords(decision: Pick<Decision, 'declined'>, live: LiveRun, nameOf: NameOf): string | null {
  return decision.declined && !isFinished(live.shown.phase) ? declinedRecord(decision.declined, nameOf) : null
}
