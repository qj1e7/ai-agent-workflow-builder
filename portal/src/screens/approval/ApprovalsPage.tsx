import { useErrorWords, useRunClock } from '../../api/context'
import { useDisplayName } from '../../api/people'
import { useRuns } from '../../api/queries'
import type { RunViewOf } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDuration } from '../../ui/format'
import { IconClock, IconReplay } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { waitingApprovals } from './approvals'
import { useWaited } from './useWaited'
import { atWords } from './waiting'
import styles from './ApprovalsPage.module.css'

export function ApprovalsPage() {
  const explain = useErrorWords()
  const runs = useRuns({ poll: true })

  return (
    <div className="page">
      <PageHeader title="Approvals">Runs waiting for an Approver.</PageHeader>
      {runs.data ? <WaitingList runs={waitingApprovals(runs.data)} /> : null}
      {!runs.data && runs.isError ? (
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load the approvals. {explain(runs.error)}</InlineMessage>
          <Button icon={IconReplay} onClick={() => void runs.refetch()} loading={runs.isFetching}>
            Try again
          </Button>
        </div>
      ) : null}
      {!runs.data && !runs.isError ? (
        <div className={`panel ${styles['padded']}`}>
          <Skeleton lines={3} label="Loading approvals" />
        </div>
      ) : null}
    </div>
  )
}

function WaitingList({ runs }: { runs: RunViewOf<'awaiting_approval'>[] }) {
  if (runs.length === 0) {
    return (
      <EmptyState title="Nothing is waiting for an Approver." action={<ButtonLink to="/">See all runs</ButtonLink>}>
        A run appears here when it reaches the approval gate.
      </EmptyState>
    )
  }
  return (
    <ul className={`panel ${styles['rows']}`}>
      {runs.map((run) => (
        <li key={run.run_id}>
          <WaitingRun run={run} />
        </li>
      ))}
    </ul>
  )
}

function WaitingRun({ run }: { run: RunViewOf<'awaiting_approval'> }) {
  const nameOf = useDisplayName()
  const clock = useRunClock()
  const waited = useWaited(run.run_id, run.updated_at)
  const starter = nameOf(run.started_by)
  const step = run.approval.steps.find((each) => each.status === 'open') ?? run.approval.steps[0]

  return (
    <div className={styles['row']}>
      <div className={styles['what']}>
        <h2>{run.use_case_name}</h2>
        <p className="muted">
          Started by {starter} {atWords(run.started_at, clock.now(run.run_id))}.{' '}
          {step ? `${step.label}: anyone except ${starter} can decide.` : null}
        </p>
      </div>
      <span className={styles['waited']}>
        <IconClock size={16} />
        Waiting {formatDuration(waited)}
      </span>
      <div className={styles['open']}>
        <ButtonLink to={run.approval.link}>Open the approval page</ButtonLink>
      </div>
    </div>
  )
}
