import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isConflict, refusalOf, useApproval, useDecide, useMe } from '../../api/queries'
import type { ApprovalView, Verdict } from '../../api/types'
import { decisionRequest, decisionState, sentBy, type DecisionAttempt, type DecisionState, type Sender } from './decisionState'

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
 * A decision belongs to the person who sent it on that approval: after a user switch the next person starts clean.
 */
export function useDecision(approvalId: string | null): Decision {
  const approval = useApproval(approvalId ?? '', { poll: true, enabled: approvalId !== null })
  const decide = useDecide(approvalId ?? '')
  const user = useMe().data
  const explain = useErrorWords()
  const [sender, setSender] = useState<Sender | null>(null)
  const latch = useLatch()
  const own = sentBy(sender, user, approvalId ?? '')
  const view = approvalId === null ? undefined : approval.data
  const state = view ? decisionState(view, user, attemptOf(decide, sender, explain)) : null

  return {
    view,
    state,
    loadError: approval.error,
    sending: own && decide.isPending ? decide.variables.verdict : null,
    sent: own && decide.isSuccess ? decide.variables.digest : null,
    send(verdict) {
      const request = view && state ? decisionRequest(view, state.panel, verdict) : null
      if (!request || approvalId === null || !user) return
      latch.run((settled) => {
        setSender({ user: user.id, approvalId })
        decide.mutate(request, { onSettled: settled })
      })
    },
  }
}

function attemptOf(decide: ReturnType<typeof useDecide>, sender: Sender | null, explain: (error: unknown) => string): DecisionAttempt {
  if (sender === null) return { kind: 'none' }
  if (decide.isSuccess) return { kind: 'recorded', sender, sent: decide.variables, out: decide.data }
  if (!decide.isError) return { kind: 'none' }
  const refusal = refusalOf(decide.error)
  if (refusal) return { kind: 'refused', sender, refusal }
  if (isConflict(decide.error)) return { kind: 'conflict', sender }
  return { kind: 'failed', sender, message: explain(decide.error) }
}
