import { refusalLabel } from '../../api/labels'
import type {
  ApprovalStepView,
  ApprovalView,
  DecisionIn,
  DecisionOut,
  DecisionView,
  DevUser,
  Refusal,
  RefusalOut,
  Verdict,
} from '../../api/types'
import type { SpineBlock } from '../../ui/Spine'
import { atWords } from './waiting'

export type DecisionAttempt =
  | { kind: 'none' }
  | { kind: 'recorded'; sent: DecisionIn; out: DecisionOut }
  | { kind: 'refused'; refusal: RefusalOut }
  | { kind: 'conflict' }
  | { kind: 'failed'; message: string }

export type Notice =
  | { kind: 'refused'; message: string }
  | { kind: 'conflict' }
  | { kind: 'failed'; message: string }

export type DecisionPanel =
  | { kind: 'can_decide'; step: ApprovalStepView }
  | { kind: 'cannot_decide'; refusal: Refusal; words: string; hint: string | null }
  | { kind: 'decided'; verdict: Verdict; by: string; at: string }

export interface DecisionState {
  steps: ApprovalStepView[]
  panel: DecisionPanel
  notice: Notice | null
}

function withDecision(steps: readonly ApprovalStepView[], decision: DecisionView): ApprovalStepView[] {
  return steps.map((step) =>
    step.index === decision.step
      ? {
          ...step,
          status: decision.verdict === 'approve' ? 'approved' : 'declined',
          decided_by: decision.by,
          decided_at: decision.at,
        }
      : step,
  )
}

function closedBy(steps: readonly ApprovalStepView[]): DecisionPanel | null {
  const declined = steps.find((step) => step.status === 'declined')
  if (declined) {
    return { kind: 'decided', verdict: 'decline', by: declined.decided_by ?? '', at: declined.decided_at ?? '' }
  }
  const last = steps.at(-1)
  if (last && steps.every((step) => step.status === 'approved')) {
    return { kind: 'decided', verdict: 'approve', by: last.decided_by ?? '', at: last.decided_at ?? '' }
  }
  return null
}

function refusalHint(refusal: Refusal, user: DevUser | undefined): string | null {
  switch (refusal) {
    case 'own_work':
      return 'Send the link to another Approver.'
    case 'not_an_approver':
      return user
        ? `You are signed in as ${user.display}, who is not an Approver. Send the link to an Approver.`
        : 'Send the link to an Approver.'
    default:
      return null
  }
}

function cannotDecide(refusal: Refusal, user: DevUser | undefined): DecisionPanel {
  return { kind: 'cannot_decide', refusal, words: refusalLabel[refusal], hint: refusalHint(refusal, user) }
}

function noticeOf(attempt: DecisionAttempt): Notice | null {
  switch (attempt.kind) {
    case 'refused':
      return { kind: 'refused', message: attempt.refusal.message }
    case 'conflict':
      return { kind: 'conflict' }
    case 'failed':
      return { kind: 'failed', message: attempt.message }
    default:
      return null
  }
}

export function decisionState(view: ApprovalView, user: DevUser | undefined, attempt: DecisionAttempt): DecisionState {
  const steps = attempt.kind === 'recorded' ? withDecision(view.steps, attempt.out.decision) : view.steps
  const notice = noticeOf(attempt)
  const closed = closedBy(steps)
  if (closed) return { steps, panel: closed, notice }

  const open = steps.find((step) => step.status === 'open')
  if (!open) return { steps, panel: cannotDecide(view.why_not ?? 'invalid_decisions', user), notice }
  if (attempt.kind === 'recorded') return { steps, panel: cannotDecide('decided_earlier_step', user), notice }
  if (view.you_can_decide) return { steps, panel: { kind: 'can_decide', step: open }, notice }
  return { steps, panel: cannotDecide(view.why_not ?? 'not_open', user), notice }
}

export function decisionRequest(view: ApprovalView, panel: DecisionPanel, verdict: Verdict): DecisionIn | null {
  return panel.kind === 'can_decide' ? { digest: view.digest, step: panel.step.index, verdict } : null
}

export function stepBlocks(
  steps: readonly ApprovalStepView[],
  nameOf: (userId: string) => string,
  nowMs: number,
): SpineBlock[] {
  return steps.map((step): SpineBlock => {
    const by = nameOf(step.decided_by ?? '')
    const at = step.decided_at ? `Decided ${atWords(step.decided_at, nowMs)}.` : undefined
    const base = { key: String(step.index), name: step.label, kind: 'approval' as const }
    switch (step.status) {
      case 'approved':
        return { ...base, state: { kind: 'approved', by }, ...(at ? { description: at } : {}) }
      case 'declined':
        return { ...base, state: { kind: 'declined', by }, ...(at ? { description: at } : {}) }
      case 'open':
        return { ...base, state: { kind: 'waiting' } }
      case 'waiting':
        return { ...base, state: { kind: 'not_reached' }, description: 'Opens after the earlier step is decided.' }
    }
  })
}
