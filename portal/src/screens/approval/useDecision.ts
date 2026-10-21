import { errorWords } from '../../api/errors'
import { isConflict, refusalOf, useApproval, useDecide, useDevUsers } from '../../api/queries'
import { useDevUser } from '../../api/session'
import type { ApprovalView, Verdict } from '../../api/types'
import { decisionRequest, decisionState, type DecisionAttempt, type DecisionState } from './decisionState'

export interface Decision {
  /** GET /api/v1/approvals/{id} for the signed-in user: the actions, the steps, you_can_decide and why_not. */
  readonly view: ApprovalView | undefined
  /** Null until the record loads, and while there is no approval to decide. */
  readonly state: DecisionState | null
  readonly loadError: unknown
  /** The verdict on its way, or null. */
  readonly sending: Verdict | null
  /** The digest of the decision the platform recorded for this viewer, or null. */
  readonly sent: string | null
  /** Posts the record's digest, the open step and the verdict, only when the record says this viewer can decide. */
  send(this: void, verdict: Verdict): void
}

/**
 * The one way to decide an approval, for the approval page and the Tracker's gate panel alike. A null id fetches
 * nothing. The record polls while it is in use, so a decision made in Teams or on another screen shows here too.
 */
export function useDecision(approvalId: string | null): Decision {
  const approval = useApproval(approvalId ?? '', { poll: true, enabled: approvalId !== null })
  const decide = useDecide(approvalId ?? '')
  const userId = useDevUser()
  const user = useDevUsers().data?.find((candidate) => candidate.id === userId)
  const view = approvalId === null ? undefined : approval.data
  const state = view ? decisionState(view, user, attemptOf(decide)) : null

  return {
    view,
    state,
    loadError: approval.error,
    sending: decide.isPending ? decide.variables.verdict : null,
    sent: decide.isSuccess ? decide.variables.digest : null,
    send(verdict) {
      const request = view && state ? decisionRequest(view, state.panel, verdict) : null
      if (request && !decide.isPending) decide.mutate(request)
    },
  }
}

function attemptOf(decide: ReturnType<typeof useDecide>): DecisionAttempt {
  if (decide.isSuccess) return { kind: 'recorded', sent: decide.variables, out: decide.data }
  if (!decide.isError) return { kind: 'none' }
  const refusal = refusalOf(decide.error)
  if (refusal) return { kind: 'refused', refusal }
  if (isConflict(decide.error)) return { kind: 'conflict' }
  return { kind: 'failed', message: errorWords(decide.error) }
}
