import { useState, type ReactNode } from 'react'
import { useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useRunClock } from '../../api/context'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { isConflict, refusalOf, useApproval, useDecide, useDevUsers, useRun } from '../../api/queries'
import { useDevUser } from '../../api/session'
import type { ApprovalView, RunView, Verdict } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDuration, shortDigest } from '../../ui/format'
import { IconCheck, IconClock, IconCopy, IconDoor, IconLock, IconReplay, IconShield, IconX } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { Spine } from '../../ui/Spine'
import { decisionRequest, decisionState, stepBlocks, type DecisionAttempt, type DecisionPanel } from './decisionState'
import { ticketStatus, type TicketStatus } from './ticketStatus'
import { useWaited } from './useWaited'
import { atWords } from './waiting'
import { systemsWritten } from './writeAction'
import { WriteTicket } from './WriteTicket'
import styles from './ApprovalPage.module.css'

const TITLE = 'Approve a write to Jira'

export function ApprovalPage() {
  const { approvalId = '' } = useParams()
  const approval = useApproval(approvalId, { poll: true })

  if (approval.data) return <ApprovalContent view={approval.data} />

  const notFound = approval.error instanceof ApiError && approval.error.status === 404
  if (notFound) {
    return (
      <Frame title="Approval not found">
        <EmptyState
          title="There is no approval at this address."
          action={<ButtonLink to="/approvals">See approvals waiting for a decision</ButtonLink>}
        >
          The link may be mistyped, or the request may have been removed.
        </EmptyState>
      </Frame>
    )
  }
  if (approval.isError) {
    return (
      <Frame title={TITLE}>
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load this approval. {errorWords(approval.error)}</InlineMessage>
          <Button icon={IconReplay} onClick={() => void approval.refetch()} loading={approval.isFetching}>
            Try again
          </Button>
        </div>
      </Frame>
    )
  }
  return (
    <Frame title={TITLE}>
      <div className={styles['layout']}>
        <div className={styles['skeletonPane']}>
          <Skeleton lines={5} label="Loading the approval" />
        </div>
        <div className={styles['skeletonPane']}>
          <Skeleton lines={3} label="Loading your decision" />
        </div>
      </div>
    </Frame>
  )
}

interface FrameProps {
  title: string
  aside?: ReactNode
  lede?: ReactNode
  children: ReactNode
}

function Frame({ title, aside, lede, children }: FrameProps) {
  return (
    <div className="page">
      <div className={styles['frame']}>
        <PageHeader title={title} aside={aside}>
          {lede}
        </PageHeader>
        {children}
      </div>
    </div>
  )
}

function attemptOf(decide: ReturnType<typeof useDecide>): DecisionAttempt {
  if (decide.isSuccess) return { kind: 'recorded', sent: decide.variables, out: decide.data }
  if (!decide.isError) return { kind: 'none' }
  const refusal = refusalOf(decide.error)
  if (refusal) return { kind: 'refused', refusal }
  if (isConflict(decide.error)) return { kind: 'conflict' }
  return { kind: 'failed', message: errorWords(decide.error) }
}

function ApprovalContent({ view }: { view: ApprovalView }) {
  const userId = useDevUser()
  const users = useDevUsers().data
  const nameOf = useDisplayName()
  const clock = useRunClock()
  const run = useRun(view.run_id, { poll: true }).data
  const decide = useDecide(view.approval_id)
  const state = decisionState(view, users?.find((user) => user.id === userId), attemptOf(decide))
  const now = clock.now(view.run_id)
  const status = ticketStatus(state.panel, run)
  const lede = run ? `${run.use_case_name}, started by ${nameOf(run.started_by)} ${atWords(run.started_at, now)}.` : null

  function send(verdict: Verdict) {
    const request = decisionRequest(view, state.panel, verdict)
    if (request) decide.mutate(request)
  }

  return (
    <Frame
      title={TITLE}
      lede={lede}
      aside={<ButtonLink to={`/runs/${view.run_id}`}>Watch the run</ButtonLink>}
    >
      <Banner panel={state.panel} status={status} run={run} view={view} nameOf={nameOf} now={now} />
      <div className={styles['layout']}>
        <section aria-labelledby="written-heading" className={styles['written']}>
          <h2 id="written-heading">Exactly what will be written</h2>
          {view.actions.length === 0 ? (
            <p className="muted">This request has nothing to write.</p>
          ) : (
            view.actions.map((action, index) => (
              <WriteTicket key={index} action={action} position={{ index, total: view.actions.length }} status={status} />
            ))
          )}
        </section>
        <section aria-labelledby="decision-heading" className={`panel ${styles['decision']}`}>
          <h2 id="decision-heading">Your decision</h2>
          <Spine
            blocks={stepBlocks(state.steps, nameOf, now)}
            orientation="vertical"
            compact
            showDescriptions
            label="Approval steps"
          />
          <DecisionBody
            panel={state.panel}
            notice={state.notice}
            view={view}
            systems={systemsWritten(view.actions)}
            sending={decide.isPending ? (decide.variables.verdict) : null}
            sent={decide.isSuccess ? decide.variables.digest : null}
            onDecide={send}
          />
        </section>
      </div>
    </Frame>
  )
}

interface BannerProps {
  panel: DecisionPanel
  status: TicketStatus
  run: RunView | undefined
  view: ApprovalView
  nameOf: (id: string) => string
  now: number
}

function Banner({ panel, status, run, view, nameOf, now }: BannerProps) {
  if (panel.kind === 'decided') {
    const who = `${nameOf(panel.by)} ${atWords(panel.at, now)}`
    if (panel.verdict === 'decline') {
      return (
        <div className={`${styles['banner']} ${styles['bannerDeclined']}`}>
          <IconX size={22} />
          <p>
            <strong>Declined by {who}.</strong> Nothing was written.
          </p>
        </div>
      )
    }
    return (
      <div className={`${styles['banner']} ${styles['bannerApproved']}`}>
        <IconCheck size={22} />
        <p>
          <strong>Approved by {who}.</strong> {status.kind === 'written' ? `Written as ${status.key}.` : 'The run is writing the ticket now.'}
        </p>
      </div>
    )
  }
  return (
    <div className={`${styles['banner']} ${styles['bannerOpen']}`}>
      <IconDoor size={22} />
      <p>
        <strong>The run is paused at the approval gate.</strong> Nothing has been written.
      </p>
      {run?.state === 'awaiting_approval' ? <Waited runId={view.run_id} since={run.updated_at} /> : null}
    </div>
  )
}

function Waited({ runId, since }: { runId: string; since: string }) {
  const waited = useWaited(runId, since)
  return (
    <span className={styles['waited']}>
      <IconClock size={16} />
      Waiting {formatDuration(waited)}
    </span>
  )
}

interface DecisionBodyProps {
  panel: DecisionPanel
  notice: ReturnType<typeof decisionState>['notice']
  view: ApprovalView
  systems: string
  sending: Verdict | null
  sent: string | null
  onDecide: (verdict: Verdict) => void
}

function DecisionBody({ panel, notice, view, systems, sending, sent, onDecide }: DecisionBodyProps) {
  return (
    <div className={styles['body']}>
      {notice ? (
        <InlineMessage tone="error">
          {notice.kind === 'conflict' ? 'Another Approver decided this step first.' : notice.message}
        </InlineMessage>
      ) : null}
      {panel.kind === 'can_decide' ? (
        <>
          <p>
            Approving writes this request to {systems}, and nothing else. Declining stops the run without writing anything.
          </p>
          <div className={styles['actions']}>
            <Button
              variant="approve"
              icon={IconCheck}
              loading={sending === 'approve'}
              disabled={sending === 'decline'}
              onClick={() => onDecide('approve')}
            >
              Approve and write to {systems}
            </Button>
            <Button
              variant="danger-outline"
              icon={IconX}
              loading={sending === 'decline'}
              disabled={sending === 'approve'}
              onClick={() => onDecide('decline')}
            >
              Decline
            </Button>
          </div>
        </>
      ) : null}
      {panel.kind === 'cannot_decide' ? (
        <div className={styles['cannot']}>
          <p className={styles['cannotWords']}>
            <IconLock size={20} />
            <span>{panel.words}</span>
          </p>
          {panel.hint ? <p className="muted">{panel.hint}</p> : null}
          <CopyLink />
        </div>
      ) : null}
      {panel.kind === 'decided' ? (
        <ButtonLink to={`/runs/${view.run_id}`}>
          {panel.verdict === 'approve' ? 'Watch the rest of the run' : 'Open the run'}
        </ButtonLink>
      ) : null}
      <Fingerprint digest={sent ?? view.digest} show={panel.kind === 'can_decide' || sent !== null} />
      <TechnicalDetails view={view} sentDigest={sent} panel={panel} />
    </div>
  )
}

function Fingerprint({ digest, show }: { digest: string; show: boolean }) {
  if (!show) return null
  return (
    <div className={styles['fingerprint']}>
      <IconShield size={18} />
      <div>
        <p className={styles['fingerprintLine']}>
          <span>Sent with your decision</span>
          <span className={styles['digest']}>{shortDigest(digest)}</span>
        </p>
        <p className={styles['fineprint']}>A short code for the exact request on this page. If the request changes, the platform refuses your decision.</p>
      </div>
    </div>
  )
}

function TechnicalDetails({ view, sentDigest, panel }: { view: ApprovalView; sentDigest: string | null; panel: DecisionPanel }) {
  return (
    <details className={styles['details']}>
      <summary>Technical details</summary>
      <dl>
        <div>
          <dt>Approval</dt>
          <dd>{view.approval_id}</dd>
        </div>
        <div>
          <dt>Run</dt>
          <dd>{view.run_id}</dd>
        </div>
        {panel.kind === 'can_decide' ? (
          <div>
            <dt>Step to decide</dt>
            <dd>{panel.step.index}</dd>
          </div>
        ) : null}
        <div>
          <dt>{sentDigest ? 'Fingerprint sent' : 'Fingerprint'}</dt>
          <dd>{sentDigest ?? view.digest}</dd>
        </div>
      </dl>
    </details>
  )
}

function CopyLink() {
  const [result, setResult] = useState<'idle' | 'copied' | 'failed'>('idle')

  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setResult('copied')
    } catch {
      setResult('failed')
    }
  }

  return (
    <div className={styles['copy']}>
      <Button icon={result === 'copied' ? IconCheck : IconCopy} onClick={() => void copy()}>
        {result === 'copied' ? 'Link copied' : 'Copy link to this page'}
      </Button>
      <span role="status" className={styles['copyStatus']}>
        {result === 'failed' ? 'The link could not be copied. Copy it from the address bar instead.' : ''}
      </span>
    </div>
  )
}
