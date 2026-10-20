import type {
  ActivityEvent,
  ApprovalStepStatus,
  ApprovalStepView,
  FailureReason,
  FailureStage,
  ProposalView,
  RunOutcome,
  RunState,
  RunView,
  WriteActionView,
  WriteDoneView,
} from '../api/types'

export interface RunMeta {
  readonly id: string
  readonly useCaseId: string
  readonly useCaseName: string
  readonly useCaseVersion: number
  readonly startedBy: string
}

export interface ApprovalRecord {
  readonly approval_id: string
  readonly run_id: string
  readonly link: string
  readonly proposal_id: string
  readonly digest: string
  readonly actions: WriteActionView[]
  readonly steps: ApprovalStepView[]
}

export function foldApprovals(
  runId: string,
  events: readonly ActivityEvent[],
  proposals: readonly ProposalView[],
): ApprovalRecord[] {
  const records: ApprovalRecord[] = []
  let proposal: ProposalView | undefined
  for (const event of events) {
    if (event.kind === 'write_action_proposed') {
      proposal = proposals.find((candidate) => candidate.proposal_id === event.data.proposal_id)
    } else if (event.kind === 'approval_requested' && proposal) {
      records.push({
        approval_id: event.data.approval_id,
        run_id: runId,
        link: event.data.link,
        proposal_id: proposal.proposal_id,
        digest: proposal.digest,
        actions: proposal.actions,
        steps: event.data.steps,
      })
    } else if (event.kind === 'approval_decided') {
      const index = records.findIndex((record) => record.approval_id === event.data.approval_id)
      const record = records[index]
      if (record) {
        const status: ApprovalStepStatus = event.data.verdict === 'approve' ? 'approved' : 'declined'
        const steps = record.steps.map((step) =>
          step.index === event.data.step ? { ...step, status, decided_by: event.data.by, decided_at: event.ts } : step,
        )
        records[index] = { ...record, steps }
      }
    }
  }
  return records
}

interface Progress {
  phase: RunState
  attempt: number
  executionId: string
  proposal: ProposalView | undefined
  written: WriteDoneView[]
  outcome: RunOutcome
  rejectedBy: string
  rejectedStep: number
  failure: { stage: FailureStage; reason: FailureReason; retryable: boolean; message: string }
}

function freshProgress(): Progress {
  return {
    phase: 'pending',
    attempt: 1,
    executionId: '',
    proposal: undefined,
    written: [],
    outcome: 'nothing_to_write',
    rejectedBy: '',
    rejectedStep: 0,
    failure: { stage: 'pending', reason: 'AgentError', retryable: false, message: '' },
  }
}

function advance(progress: Progress, event: ActivityEvent, proposals: readonly ProposalView[]): Progress {
  switch (event.kind) {
    case 'run_created':
    case 'run_retried':
      return freshProgress()
    case 'leg_dispatched':
      return event.data.leg === 'work' ? { ...progress, attempt: event.data.attempt } : progress
    case 'step_started':
      return event.data.step === 'run_agents'
        ? { ...progress, phase: 'working', executionId: event.data.n8n_execution_id }
        : progress
    case 'write_action_proposed': {
      const proposal = proposals.find((candidate) => candidate.proposal_id === event.data.proposal_id)
      return proposal ? { ...progress, phase: 'proposed', proposal } : progress
    }
    case 'approval_requested':
      return { ...progress, phase: 'awaiting_approval' }
    case 'approval_decided':
      return event.data.verdict === 'approve' ? { ...progress, phase: 'acting' } : progress
    case 'write_action_done':
      return {
        ...progress,
        written: [
          ...progress.written,
          {
            connector: event.data.connector,
            operation: event.data.operation,
            external_reference: event.data.external_reference,
            approved_by: event.data.approved_by,
          },
        ],
      }
    case 'run_succeeded':
      return { ...progress, phase: 'succeeded', outcome: event.data.outcome }
    case 'run_rejected':
      return { ...progress, phase: 'rejected', rejectedBy: event.data.by, rejectedStep: event.data.step }
    case 'run_failed':
      return { ...progress, phase: 'failed', failure: event.data }
    default:
      return progress
  }
}

export function foldView(
  meta: RunMeta,
  events: readonly ActivityEvent[],
  proposals: readonly ProposalView[],
): RunView {
  const progress = events.reduce((state, event) => advance(state, event, proposals), freshProgress())
  const first = events[0]
  const last = events.at(-1)
  const base = {
    run_id: meta.id,
    use_case_id: meta.useCaseId,
    use_case_name: meta.useCaseName,
    use_case_version: meta.useCaseVersion,
    started_by: meta.startedBy,
    started_at: first?.ts ?? new Date(0).toISOString(),
    updated_at: last?.ts ?? new Date(0).toISOString(),
    last_seq: last?.seq ?? 0,
    events_url: `/api/v1/runs/${meta.id}/events`,
  }
  const approval = foldApprovals(meta.id, events, proposals).at(-1)
  const approvalRef = approval && { approval_id: approval.approval_id, link: approval.link, steps: approval.steps }
  const { proposal } = progress

  switch (progress.phase) {
    case 'working':
      return { ...base, state: 'working', n8n_execution_id: progress.executionId, attempt: progress.attempt }
    case 'proposed':
      return proposal ? { ...base, state: 'proposed', proposal } : { ...base, state: 'pending' }
    case 'awaiting_approval':
    case 'acting':
    case 'rejected': {
      if (!proposal || !approvalRef) return { ...base, state: 'pending' }
      if (progress.phase === 'rejected') {
        return {
          ...base,
          state: 'rejected',
          proposal,
          approval: approvalRef,
          rejected_by: progress.rejectedBy,
          step: progress.rejectedStep,
        }
      }
      return { ...base, state: progress.phase, proposal, approval: approvalRef }
    }
    case 'succeeded':
      return { ...base, state: 'succeeded', outcome: progress.outcome, written: progress.written }
    case 'failed':
      return { ...base, state: 'failed', ...progress.failure }
    case 'pending':
      return { ...base, state: 'pending' }
  }
}
