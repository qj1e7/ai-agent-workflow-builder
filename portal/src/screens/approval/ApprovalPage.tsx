import { useState, type ReactNode } from 'react'
import { useParams } from 'react-router'
import { ApiError } from '../../api/client'
import { starterName } from '../../api/labels'
import { useErrorWords, useRunClock } from '../../api/context'
import { useDisplayName } from '../../api/people'
import { useApproval, useRun } from '../../api/queries'
import type { ApprovalView, RunView, Verdict } from '../../api/types'
import { CONFLICT_WORDS } from '../../run'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDuration, shortDigest } from '../../ui/format'
import { IconCheck, IconClock, IconCopy, IconDoor, IconLock, IconReplay, IconShield, IconX } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { Spine } from '../../ui/Spine'
import { decisionState, stepBlocks, type DecisionPanel } from './decisionState'
import { ticketStatus } from './ticketStatus'
import { useDecision } from './useDecision'
import { useWaited } from './useWaited'
import { atWords } from './waiting'
import { approvalTitle, systemsWritten } from './writeAction'
import { WriteTicket } from './WriteTicket'
import styles from './ApprovalPage.module.css'

const TITLE = 'Approve a write to Jira'

export function ApprovalPage() {
  const explain = useErrorWords()
  const { approvalId = '' } = useParams()
  const approval = useApproval(approvalId, { poll: true })

  if (approval.data) return <ApprovalContent view={approval.data} />

  const notFound = approval.error instanceof ApiError && approval.error.status === 404
  if (notFound) {
    return (
      <Frame title="Approval not found">
        <EmptyState title="No approval at this address." action={<ButtonLink to="/approvals">See approvals</ButtonLink>}>
          The link may be wrong, or the request was removed.
        </EmptyState>
      </Frame>
    )
  }
  if (approval.isError) {
    return (
      <Frame title={TITLE}>
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load this approval. {explain(approval.error)}</InlineMessage>
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

function ApprovalContent({ view }: { view: ApprovalView }) {
  const nameOf = useDisplayName()
  const clock = useRunClock()
  const run = useRun(view.run_id, { poll: true }).data
  const decision = useDecision(view.approval_id)
  const state = decision.state ?? decisionState(view, undefined, { kind: 'none' }, run?.trigger)
  const now = clock.now(view.run_id)
  const lede = run
    ? `${run.use_case_name}, started by ${starterName(nameOf(run.started_by), run.trigger)} ${atWords(run.started_at, now)}.`
    : null

  return (
    <Frame
      title={approvalTitle(view.actions)}
      lede={lede}
      aside={<ButtonLink to={`/runs/${view.run_id}`}>Watch the run</ButtonLink>}
    >
      <Banner panel={state.panel} run={run} view={view} nameOf={nameOf} />
      <div className={styles['layout']}>
        <section aria-labelledby="written-heading" className={styles['written']}>
          <h2 id="written-heading">Exactly what will be written</h2>
          {view.actions.length === 0 ? (
            <p className="muted">This request has nothing to write.</p>
          ) : (
            view.actions.map((action, index) => (
              <WriteTicket
                key={index}
                action={action}
                position={{ index, total: view.actions.length }}
                status={ticketStatus(state.panel, run, index)}
              />
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
            sending={decision.sending}
            sent={decision.sent}
            onDecide={decision.send}
          />
        </section>
      </div>
    </Frame>
  )
}

interface BannerProps {
  panel: DecisionPanel
  run: RunView | undefined
  view: ApprovalView
  nameOf: (id: string) => string
}

function Banner({ panel, run, view, nameOf }: BannerProps) {
  if (panel.kind === 'decided') {
    if (panel.verdict === 'decline') {
      return (
        <div className={`${styles['banner']} ${styles['bannerDeclined']}`}>
          <IconX size={22} />
          <p>
            <strong>Declined by {nameOf(panel.by)}.</strong> Nothing was written.
          </p>
        </div>
      )
    }
    return (
      <div className={`${styles['banner']} ${styles['bannerApproved']}`}>
        <IconCheck size={22} />
        <p>
          <strong>Approved by {nameOf(panel.by)}.</strong>
        </p>
      </div>
    )
  }
  return (
    <div className={`${styles['banner']} ${styles['bannerOpen']}`}>
      <IconDoor size={22} />
      <p>
        <strong>Waiting for an Approver.</strong> Nothing has been written.
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
          {notice.kind === 'conflict' ? CONFLICT_WORDS : notice.message}
        </InlineMessage>
      ) : null}
      {panel.kind === 'can_decide' ? (
        <>
          <p>Declining stops the run and writes nothing.</p>
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
        <p className={styles['fineprint']}>A short code for this exact request.</p>
      </div>
    </div>
  )
}

function TechnicalDetails({ view, sentDigest, panel }: { view: ApprovalView; sentDigest: string | null; panel: DecisionPanel }) {
  return (
    <details className={styles['details']}>
      <summary className="disclosure">Technical details</summary>
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
        {result === 'copied' ? 'Link copied' : 'Copy link'}
      </Button>
      <span role="status" className={styles['copyStatus']}>
        {result === 'failed' ? 'We could not copy the link. Copy it from the address bar.' : ''}
      </span>
    </div>
  )
}
