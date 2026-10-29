import { useState } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isConflict, refusalOf, useDecide } from '../../api/queries'
import type { ApprovalStepView, ApprovalView, DecisionIn, Verdict } from '../../api/types'
import { CONFLICT_WORDS, lockWords, type Party } from './words'

export function openStep(approval: ApprovalView): ApprovalStepView | null {
  return approval.steps.find((step) => step.status === 'open') ?? null
}

/** What to post, or null when the platform said this person may not decide or nothing is open. Never from the stream. */
export function decisionFor(approval: ApprovalView | undefined, verdict: Verdict): DecisionIn | null {
  if (!approval?.you_can_decide) return null
  const step = openStep(approval)
  return step ? { step: step.index, verdict, digest: approval.digest } : null
}

export interface Decision {
  readonly pending: Verdict | null
  /** The verdict the platform recorded for this person on this page. */
  readonly recorded: Verdict | null
  readonly error: string | null
  decide(this: void, verdict: Verdict): void
}

/**
 * It posts only when the platform said this person may decide. A second press before the first answer is dropped.
 * A dev user switch starts clean, because it remembers who sent it.
 */
export function useDecision(approval: ApprovalView | undefined, party: Party | null, onRecorded?: (verdict: Verdict) => void): Decision {
  const mutation = useDecide(approval?.approval_id ?? '')
  const latch = useLatch()
  const user = useCacheScope()
  const errorWords = useErrorWords()
  const [sent, setSent] = useState<{ by: string; verdict: Verdict } | null>(null)
  const mine = sent !== null && sent.by === user

  function decide(verdict: Verdict): void {
    const body = decisionFor(approval, verdict)
    if (!body) return
    latch.run((settled) => {
      setSent({ by: user, verdict })
      mutation.mutate(body, {
        onSuccess: () => onRecorded?.(verdict),
        onSettled: settled,
      })
    })
  }

  let error: string | null = null
  if (mine && mutation.isError) {
    const refusal = refusalOf(mutation.error)
    if (refusal) error = lockWords(refusal.refusal, party)
    else if (isConflict(mutation.error)) error = CONFLICT_WORDS
    else error = errorWords(mutation.error)
  }
  return {
    pending: mine && mutation.isPending ? sent.verdict : null,
    recorded: mine && mutation.isSuccess ? sent.verdict : null,
    error,
    decide,
  }
}
