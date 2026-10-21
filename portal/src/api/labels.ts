import type {
  ActivityKind,
  ApprovalStepStatus,
  BlockKind,
  FailureReason,
  FailureStage,
  Refusal,
  Role,
  RunOutcome,
  RunState,
  Verdict,
} from './types'

export const runStateLabel: Record<RunState, string> = {
  pending: 'Starting',
  working: 'Working',
  proposed: 'Preparing a request',
  awaiting_approval: 'Waiting for an Approver',
  acting: 'Writing',
  succeeded: 'Done',
  rejected: 'Declined',
  failed: 'Stopped',
}

export const failureStageLabel: Record<FailureStage, string> = {
  pending: 'Starting up',
  working: 'While the agents were working',
  proposed: 'While the request was prepared',
  acting: 'While writing',
}

export const failureReasonLabel: Record<FailureReason, string> = {
  AgentError: 'An agent could not finish its work',
  WorkflowNodeError: 'A workflow step failed',
  TimedOut: 'A step took too long',
  DispatchFailed: 'The workflow engine could not be reached',
  WriteFailed: 'The write did not go through',
  SafetyDenied: 'The safety checker blocked the write',
  UnboundIntent: 'The request did not match an allowed action',
  OutOfOrderStep: 'A step ran out of order',
}

export const refusalLabel: Record<Refusal, string> = {
  own_work: 'You started this run, so another Approver must decide.',
  not_an_approver: 'Only Approvers can decide this request.',
  not_eligible: 'You are not one of the Approvers for this step.',
  decided_earlier_step: 'You already decided an earlier step, so another Approver must decide this one.',
  wrong_step: 'This is not the step that is waiting for a decision.',
  not_open: 'This request is not open for a decision.',
  stale_digest: 'The request changed after you opened this page. Reload to see what will be written.',
  invalid_decisions: 'This approval has a problem. Ask a maintainer to check it.',
}

export const approvalStepStatusLabel: Record<ApprovalStepStatus, string> = {
  waiting: 'Waiting for the earlier step',
  open: 'Waiting for an Approver',
  approved: 'Approved',
  declined: 'Declined',
}

export const verdictLabel: Record<Verdict, string> = {
  approve: 'Approved',
  decline: 'Declined',
}

export const blockKindLabel: Record<BlockKind, string> = {
  agent: 'Agent work',
  approval: 'Approval',
  write_action: 'Write',
}

export const runOutcomeLabel: Record<RunOutcome, string> = {
  written: 'Written',
  nothing_to_write: 'Nothing to write',
}

export const roleLabel: Record<Role, string> = {
  operator: 'Operator',
  approver: 'Approver',
}

const connectorNames: Record<string, string> = {
  jira: 'Jira',
  github: 'GitHub',
  confluence: 'Confluence',
  gitlab: 'GitLab',
  teams: 'Teams',
}

const operationNames: Record<string, string> = {
  create_ticket: 'Create a ticket',
  read_releases: 'Read releases',
}

function humanise(raw: string): string {
  const spaced = raw.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function connectorLabel(connector: string): string {
  return connectorNames[connector] ?? humanise(connector)
}

/** The connector whose label appears as a whole word, case-insensitive. */
export function connectorNamedIn(words: string): string | null {
  const lower = words.toLowerCase()
  for (const [connector, label] of Object.entries(connectorNames)) {
    if (new RegExp(`\\b${label.toLowerCase()}\\b`).test(lower)) return connector
  }
  return null
}

export function operationLabel(operation: string): string {
  return operationNames[operation] ?? humanise(operation)
}

/**
 * The thing an operation writes, from the contract's verb_object operation keys: create_ticket gives
 * ticket, update_page gives page. Empty when the key has no object part.
 */
export function objectNoun(operation: string): string {
  const parts = operation.split('_').filter(Boolean)
  return parts.length > 1 ? (parts.at(-1) ?? '') : ''
}

export function rolesLabel(roles: readonly Role[]): string {
  return roles.map((role) => roleLabel[role]).join(' and ')
}

const plumbingKinds: ReadonlySet<ActivityKind> = new Set<ActivityKind>([
  'leg_dispatched',
  'step_started',
  'step_finished',
  'step_retried',
])

export function isPlumbingKind(kind: ActivityKind): boolean {
  return plumbingKinds.has(kind)
}
