import { useEffect, useRef, useState, type RefObject } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { displayName, usePeople } from '../../api/people'
import { isOperator } from '../../api/me'
import { useApproval, useMe, useModelOff, useRun, useTroubleshoot, useUseCase } from '../../api/queries'
import type { ApprovalView, Me, RunView, UseCaseView } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { PRODUCT } from '../../shell/product'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { useFromChat } from '../../ui/fromChat'
import { motionAllowed } from '../../ui/motion'
import { ApprovalGate } from './ApprovalGate'
import { Chat, DECISION_ID, LastWord, NeedsYou, Typing } from './Chat'
import { askedWords, declineReasons, foundOf, partyOf, requesterOf, useDecision, yourPart, type Decision } from './decision'
import { useLiveRun, type LiveRun } from './liveRun'
import { Outcome, Troubleshooting } from './Outcome'
import { RunLine } from './RunLine'
import { isFinished, PLANNER_ID, stationsOf, type PlanBlock, type RunModel } from './runModel'
import { declinedRecord, feedTroubleOf, headlineOf, lineOf, RUN_MISSING, RUN_PROBLEM, shortTime, speakerName, writeLabel, type NameOf, type Speaker } from './words'
import styles from './RunPage.module.css'

const LANDS_ON_DECISION = new Set(['awaiting_approval', 'failed', 'rejected'])

export const POLL_FAILED_MS = 10_000

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
  return <RunView run={latest} useCase={useCase.data} live={live} fromApproval={fromApproval} detail={{ choice: detail, choose: setDetail }} />
}

/** After a failure the stream may close. When the run has moved on without it, as after a retry, reconnect now. */
export function useReconnectWhenBehind(behind: boolean, restart: () => void): void {
  useEffect(() => {
    if (behind) restart()
  }, [behind, restart])
}

export function approvalIdOf(run: RunView, model: RunModel): string | null {
  if (model.approvalId) return model.approvalId
  return 'approval' in run ? run.approval.approval_id : null
}

export function useNameOf(model: RunModel): NameOf {
  const people = usePeople()
  return (id) => model.people[id] ?? displayName(people, id)
}

export function planOf(useCase: UseCaseView | undefined): PlanBlock[] | null {
  return useCase ? useCase.plan.map((block) => ({ name: block.name, kind: block.kind })) : null
}

function backTo(useCase: UseCaseView | undefined): string {
  return useCase?.template === 'software_watchlist' ? '/software' : '/workflows'
}

function workingNow(model: RunModel): { speaker: Speaker; thinking: boolean } {
  const { spot, agents, phase } = model
  if (phase.state === 'acting') return { speaker: { kind: 'platform' }, thinking: false }
  if (spot.at === 'agent') {
    const agent = agents[spot.index]
    if (agent) return { speaker: { kind: 'agent', agent }, thinking: false }
  }
  return { speaker: { kind: 'agent', agent: { id: PLANNER_ID, display: 'Planner' } }, thinking: true }
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
  /** Whether the agents' conversation is open, once the person chose. Null follows the run. */
  readonly detail: { readonly choice: boolean | null; readonly choose: (open: boolean) => void }
}

const WORKING = new Set<RunModel['phase']['state']>(['pending', 'working', 'proposed', 'acting'])

/** The default level follows the run: the conversation is open while the agents work, and folded once the run needs the person or is over. */
function detailOpen(choice: boolean | null, model: RunModel): boolean {
  return choice ?? WORKING.has(model.phase.state)
}

function RunView({ run, useCase, live, fromApproval, detail }: RunViewProps) {
  const { shown, head, loadedUpTo } = live
  const me = useMe().data
  const fromChat = useFromChat()
  const nameOf = useNameOf(head)
  const [lands] = useState(() => fromApproval || LANDS_ON_DECISION.has(shown.phase.state))
  const chatList = useRef<HTMLOListElement>(null)

  const approvalId = approvalIdOf(run, head)
  const waiting = shown.phase.state === 'awaiting_approval'
  const approval = useApproval(approvalId ?? '', { poll: waiting, enabled: approvalId !== null && (waiting || head.phase.state === 'awaiting_approval') })
  const attempt = head.chat.filter((item) => item.kind === 'retried').length
  const showFailure = shown.phase.state === 'failed' && head.phase.state === 'failed'
  const troubleshoot = useTroubleshoot(run.run_id, showFailure, attempt)

  const party = partyOf(approval.data, me?.id)
  const saidByMe = me ? shown.chat.findLast((item) => item.kind === 'decided' && item.by === me.id) : undefined
  const open = detailOpen(detail.choice, shown)
  const decision = useDecision(approval.data, party)
  const answered = decision.recorded !== null && !waiting && !WORKING.has(shown.phase.state)
  const focused = useRef(false)
  useEffect(() => {
    if (!answered || focused.current) return
    focused.current = true
    const line = chatList.current?.querySelector<HTMLElement>(`[data-gate-said="${saidByMe?.seq ?? ''}"]`)
    ;(open ? line : document.querySelector<HTMLElement>('main h1'))?.focus({ preventScroll: true })
  })

  const stations = stationsOf(shown, planOf(useCase), writeLabel)
  const proposal = approval.data && waiting ? approval.data.actions : null
  const headline = headlineOf(shown, stations, proposal)
  const arrivedLive = shown.spotSeq > loadedUpTo ? (stations.findLast((station) => station.state !== 'todo')?.key ?? null) : null
  const newest = shown.chat.at(-1)
  const announce = newest && newest.seq > loadedUpTo ? lineOf(newest, nameOf, run.trigger) : null

  useEffect(() => {
    document.title = `${headline.text} · ${PRODUCT}`
  }, [headline.text])

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


  useFollowUntilScrolled(newest?.seq ?? 0, loadedUpTo, chatList)

  const working = WORKING.has(shown.phase.state)
  const resting = working ? <Typing {...workingNow(shown)} /> : null
  const last = (
    <LastWordFor
      model={shown}
      approval={approval.data}
      found={foundOf(head.found, approval.data?.found)}
      decision={decision}
      troubleshoot={troubleshoot}
      nameOf={nameOf}
      me={me}
      runId={run.run_id}
      reasons={declineReasons(useCase?.template)}
    />
  )

  return (
    <div className={styles['page']}>
      {fromChat ? null : (
        <Link to={backTo(useCase)} className={styles['back']}>
          <span aria-hidden="true">‹</span>
          {run.use_case_name}
        </Link>
      )}
      <div className={styles['head']}>
        <h1 tabIndex={-1} data-page-moves-focus={lands || undefined}>
          {headline.text}
        </h1>
        <span className={cx(styles['pill'], styles[headline.pill.tone])}>{headline.pill.label}</span>
      </div>
      <p className={styles['status']} role="status">
        {statusWords(decision, live, nameOf)}
      </p>
      <RunLine stations={stations} arrivedLive={arrivedLive} startedAt={shortTime(run.started_at)} nameOf={nameOf} />
      {working ? null : <NeedsYou>{last}</NeedsYou>}
      <details className={styles['detail']} open={open}>
        <summary
          className={styles['detailToggle']}
          onClick={(event) => {
            event.preventDefault()
            detail.choose(!open)
          }}
        >
          {open ? 'Hide what each agent did' : 'Show what each agent did'}
        </summary>
        <Chat ref={chatList} items={shown.chat} loadedUpTo={loadedUpTo} nameOf={nameOf} trigger={run.trigger} last={resting} />
      </details>
      <div className="visually-hidden" aria-live="polite">
        {announce ? `${speakerName(announce.speaker)}: ${announce.text}` : ''}
      </div>
    </div>
  )
}

/** What the page says right after this person decided, before the run's own events catch up. A decline gives its record. */
export function statusWords(decision: Pick<Decision, 'recorded' | 'declined'>, live: LiveRun, nameOf: NameOf): string {
  if (live.connection.is === 'reconnecting') return 'Lost the live connection. Trying again.'
  if (live.connection.is === 'closed') return 'Stopped following this run. Reload the page to see what changed.'
  if (isFinished(live.shown.phase)) return ''
  if (decision.declined) return declinedRecord(decision.declined, nameOf)
  if (decision.recorded === 'approve') return 'Approved. The platform is writing now.'
  return ''
}

interface LastWordForProps {
  readonly model: RunModel
  readonly approval: ApprovalView | undefined
  readonly found: string
  readonly decision: ReturnType<typeof useDecision>
  readonly troubleshoot: ReturnType<typeof useTroubleshoot>
  readonly nameOf: NameOf
  readonly me: Me | undefined
  readonly runId: string
  readonly reasons: readonly string[]
}

function LastWordFor({ model, approval, found, decision, troubleshoot, nameOf, me, runId, reasons }: LastWordForProps) {
  const modelOff = useModelOff()
  const { phase } = model
  switch (phase.state) {
    case 'awaiting_approval':
      return (
        <LastWord speaker={{ kind: 'gate' }}>
          {approval ? (
            <ApprovalGate
              approval={approval}
              page={{ found, part: yourPart(approval, partyOf(approval, me?.id), nameOf), askedBy: askedWords(approval, nameOf) }}
              decision={decision}
              reasons={reasons}
              requester={nameOf(requesterOf(approval))}
            />
          ) : (
            <p className="muted" role="status">
              Loading what will be written
            </p>
          )}
        </LastWord>
      )
    case 'failed':
      return (
        <LastWord speaker={{ kind: 'troubleshooter' }}>
          <Troubleshooting
            runId={runId}
            failure={phase}
            advice={troubleshoot.data}
            loading={troubleshoot.isPending}
            me={me ? { id: me.id, name: me.display, operator: isOperator(me) } : undefined}
            reports={model.reports}
            nameOf={nameOf}
            modelOff={modelOff}
          />
        </LastWord>
      )
    case 'succeeded':
    case 'rejected':
      return (
        <LastWord speaker={{ kind: 'app' }}>
          <Outcome model={model} nameOf={nameOf} />
        </LastWord>
      )
    default:
      return null
  }
}
