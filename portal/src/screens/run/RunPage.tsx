import { useEffect, useRef, useState, type RefObject } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { displayName, usePeople } from '../../api/people'
import { useApproval, useMe, useRun, useTroubleshoot, useUseCase } from '../../api/queries'
import type { ApprovalView, RunView, UseCaseView, Verdict } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { PRODUCT } from '../../shell/product'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { ApprovalGate } from './ApprovalGate'
import { Chat, LastWord, Typing } from './Chat'
import { useDecision } from './decision'
import { motionAllowed, useLiveRun, type LiveRun } from './liveRun'
import { Outcome, Troubleshooting } from './Outcome'
import { RunLine } from './RunLine'
import { PLANNER_ID, reachOf, stationsOf, type PlanBlock, type RunModel } from './runModel'
import { headlineOf, lineOf, lockWords, shortTime, speakerName, writeLabel, type NameOf, type Party, type Speaker } from './words'
import styles from './RunPage.module.css'

/** Opening a run that needs someone lands on the decision, with the run already drawn. */
const LANDS_ON_DECISION = new Set(['awaiting_approval', 'failed', 'rejected'])

const POLL_FAILED_MS = 10_000

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

function Missing({ what }: { what: 'run' | 'approval' }) {
  return (
    <>
      <PageHead heading={what === 'run' ? 'Run not found' : 'Approval not found'} lead={`There is no ${what} at this address.`} />
      <p>
        <Link to="/">Go to Home</Link>
      </p>
    </>
  )
}

function Problem({ onRetry }: { onRetry: () => void }) {
  return (
    <>
      <PageHead heading="We couldn't load this run" lead="Check your connection, or try again in a moment." />
      <Button onClick={onRetry}>Try again</Button>
    </>
  )
}

export function RunRoute() {
  const { runId = '' } = useParams()
  return <RunPage key={runId} runId={runId} fromApproval={false} />
}

/** The link in every Teams approval message. It opens the run page at the decision. */
export function ApprovalRoute() {
  const { approvalId = '' } = useParams()
  const approval = useApproval(approvalId)
  if (approval.isPending) return <Loading />
  if (approval.isError) return notFound(approval.error) ? <Missing what="approval" /> : <Problem onRetry={() => void approval.refetch()} />
  return <RunPage key={approval.data.run_id} runId={approval.data.run_id} fromApproval />
}

function RunPage({ runId, fromApproval }: { runId: string; fromApproval: boolean }) {
  const { live, restart } = useLiveRun(runId)
  const failed = live.head.phase.state === 'failed'
  const run = useRun(runId, { poll: failed ? POLL_FAILED_MS : false })
  const useCase = useUseCase(run.data?.use_case_id ?? live.head.useCaseId ?? '')
  const lastSeq = run.data?.last_seq ?? 0
  const behind = failed && live.loaded && lastSeq > live.head.seq

  // The stream can close after a failure. If the run moved on without it, as after a retry, reconnect now.
  useEffect(() => {
    if (behind) restart()
  }, [behind, restart])

  if (run.isError) return notFound(run.error) ? <Missing what="run" /> : <Problem onRetry={() => void run.refetch()} />
  const ready = run.data !== undefined && (live.loaded || live.connection.is === 'live' || live.connection.is === 'settled')
  if (!ready) return <Loading />
  return <RunView run={run.data} useCase={useCase.data} live={live} fromApproval={fromApproval} />
}

function approvalIdOf(run: RunView, model: RunModel): string | null {
  if (model.approvalId) return model.approvalId
  return 'approval' in run ? run.approval.approval_id : null
}

function useNameOf(model: RunModel): NameOf {
  const people = usePeople()
  return (id) => model.people[id] ?? displayName(people, id)
}

function planOf(useCase: UseCaseView | undefined): PlanBlock[] | null {
  return useCase ? useCase.plan.map((block) => ({ name: block.name, kind: block.kind })) : null
}

function backTo(useCase: UseCaseView | undefined): string {
  return useCase?.template === 'software_watchlist' ? '/software' : '/workflows'
}

/** Who is working now, for the typing row at the end of the chat. */
function workingNow(model: RunModel): { speaker: Speaker; thinking: boolean } {
  const { spot, agents, phase } = model
  if (phase.state === 'acting') return { speaker: { kind: 'platform' }, thinking: false }
  if (spot.at === 'agent') {
    const agent = agents[spot.index]
    if (agent) return { speaker: { kind: 'agent', agent }, thinking: false }
  }
  return { speaker: { kind: 'agent', agent: { id: PLANNER_ID, display: 'Planner' } }, thinking: true }
}

/** Follows the newest message while the run plays, until the person scrolls the page themselves. */
function useFollow(newest: number, quietUpTo: number, list: RefObject<HTMLOListElement | null>): void {
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
    if (!following.current || newest <= quietUpTo) return
    list.current?.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: motionAllowed() ? 'smooth' : 'auto' })
  }, [newest, quietUpTo, list])
}

interface RunViewProps {
  readonly run: RunView
  readonly useCase: UseCaseView | undefined
  readonly live: LiveRun
  readonly fromApproval: boolean
}

function RunView({ run, useCase, live, fromApproval }: RunViewProps) {
  const { shown, head, quietUpTo } = live
  const me = useMe().data
  const nameOf = useNameOf(head)
  const [lands] = useState(() => fromApproval || LANDS_ON_DECISION.has(shown.phase.state))
  const chatList = useRef<HTMLOListElement>(null)
  const focusDecided = useRef(false)

  const approvalId = approvalIdOf(run, head)
  const waiting = shown.phase.state === 'awaiting_approval'
  const approval = useApproval(approvalId ?? '', { poll: waiting, enabled: approvalId !== null && (waiting || head.phase.state === 'awaiting_approval') })
  const attempt = head.chat.filter((item) => item.kind === 'retried').length
  const showFailure = shown.phase.state === 'failed' && head.phase.state === 'failed'
  const troubleshoot = useTroubleshoot(run.run_id, showFailure, attempt)

  const party: Party | null = me
    ? { startedIt: run.started_by === me.id, retriedIt: head.retriedBy.includes(me.id), schedule: run.trigger === 'schedule' }
    : null
  const decision = useDecision(approval.data, party, () => {
    focusDecided.current = true
  })

  const stations = stationsOf(shown, planOf(useCase), writeLabel)
  const reach = reachOf(stations)
  const proposal = approval.data && waiting ? approval.data.actions : null
  const headline = headlineOf(shown, stations, proposal)
  const arrived = shown.spotSeq > quietUpTo ? (stations.find((station) => station.state === 'now' || station.state === 'wait')?.key ?? null) : null
  const newest = shown.chat.at(-1)
  const announce = newest && newest.seq > quietUpTo ? lineOf(newest, nameOf, run.trigger) : null

  useEffect(() => {
    document.title = `${headline.text} · ${PRODUCT}`
  }, [headline.text])

  useEffect(() => {
    if (!lands) return
    const decisionArea = document.getElementById('decision')
    if (!decisionArea) {
      document.querySelector<HTMLElement>('main h1')?.focus({ preventScroll: true })
      return
    }
    decisionArea.focus({ preventScroll: true })
    decisionArea.scrollIntoView({ block: 'start' })
  }, [lands])

  // After a yes or a no here, focus moves to what the approval gate said, so the page does not jump away from it.
  useEffect(() => {
    if (!focusDecided.current || !me) return
    const said = shown.chat.findLast((item) => item.kind === 'decided' && item.by === me.id)
    if (!said) return
    focusDecided.current = false
    chatList.current?.querySelector<HTMLElement>(`[data-gate-said="${said.seq}"]`)?.focus()
  }, [shown.chat, me])

  useFollow(newest?.seq ?? 0, quietUpTo, chatList)

  return (
    <div className={styles['page']}>
      <Link to={backTo(useCase)} className={styles['back']}>
        <span aria-hidden="true">‹</span>
        {run.use_case_name}
      </Link>
      <div className={styles['head']}>
        <h1 tabIndex={-1} data-focus={lands ? 'page' : undefined}>
          {headline.text}
        </h1>
        <span className={cx(styles['pill'], styles[headline.pill.tone])}>{headline.pill.label}</span>
      </div>
      <p className={styles['status']} role="status">
        {statusWords(decision.recorded, live)}
      </p>
      <RunLine stations={stations} reach={reach} arrived={arrived} startedAt={shortTime(run.started_at)} nameOf={nameOf} />
      <Chat
        ref={chatList}
        items={shown.chat}
        quietUpTo={quietUpTo}
        nameOf={nameOf}
        trigger={run.trigger}
        last={<LastWordFor model={shown} approval={approval.data} lock={lockWords(approval.data?.why_not ?? null, party)} decision={decision} troubleshoot={troubleshoot} nameOf={nameOf} />}
      />
      <div className="visually-hidden" aria-live="polite">
        {announce ? `${speakerName(announce.speaker)}: ${announce.text}` : ''}
      </div>
    </div>
  )
}

function statusWords(recorded: Verdict | null, live: LiveRun): string {
  if (live.connection.is === 'reconnecting') return 'Lost the live connection. Trying again.'
  if (recorded === 'approve') return 'Approved. The platform is writing now.'
  if (recorded === 'decline') return 'Declined. Nothing will be written.'
  return ''
}

interface LastWordForProps {
  readonly model: RunModel
  readonly approval: ApprovalView | undefined
  readonly lock: string
  readonly decision: ReturnType<typeof useDecision>
  readonly troubleshoot: ReturnType<typeof useTroubleshoot>
  readonly nameOf: NameOf
}

/** The last word goes to whoever needs the person: the gate with the decision, the troubleshooter with the reason, or Workflow Builder with the outcome. */
function LastWordFor({ model, approval, lock, decision, troubleshoot, nameOf }: LastWordForProps) {
  const { phase } = model
  switch (phase.state) {
    case 'awaiting_approval':
      return (
        <LastWord speaker={{ kind: 'gate' }}>
          {approval ? (
            <ApprovalGate approval={approval} lock={lock} decision={decision} />
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
          <Troubleshooting failure={phase} advice={troubleshoot.data} loading={troubleshoot.isPending} />
        </LastWord>
      )
    case 'succeeded':
    case 'rejected':
      return (
        <LastWord speaker={{ kind: 'app' }}>
          <Outcome model={model} nameOf={nameOf} />
        </LastWord>
      )
    default: {
      const now = workingNow(model)
      return <Typing speaker={now.speaker} thinking={now.thinking} />
    }
  }
}
