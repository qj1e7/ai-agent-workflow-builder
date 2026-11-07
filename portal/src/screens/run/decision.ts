import { useState } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isConflict, refusalOf, useDecide } from '../../api/queries'
import type { ApprovalStepView, ApprovalView, DecisionIn, Verdict } from '../../api/types'
import { starterName } from '../../api/labels'
import { andList, CONFLICT_WORDS, lockWords, type NameOf, type Party } from './words'

export function openStep(approval: ApprovalView): ApprovalStepView | null {
  return approval.steps.find((step) => step.status === 'open') ?? null
}

/**
 * How the person is tied to the run: the owner, the starter and the retriers, the same people the gate refuses.
 * It reads the approval's own fields, so it needs no events.
 */
export function partyOf(approval: ApprovalView | undefined, me: string | undefined): Party | null {
  if (!approval || me === undefined) return null
  return {
    ownsIt: approval.owner === me,
    startedIt: approval.started_by === me,
    retriedIt: approval.retried_by.includes(me),
    schedule: approval.trigger === 'schedule',
  }
}

/** What the agents found. The activity has it for good, and the approval holds it only while the request waits. */
export function foundOf(fromActivity: string, fromApproval: string | undefined): string {
  return fromActivity !== '' ? fromActivity : (fromApproval ?? '')
}

/** Who asked: the workflow, who set it up, and whether a schedule or a person started this run. */
export function askedWords(approval: ApprovalView, nameOf: NameOf): string {
  const starter = `${starterName(nameOf(approval.started_by), approval.trigger)} started this run.`
  const retried = approval.retried_by.length > 0 ? ` ${andList(approval.retried_by.map(nameOf))} retried it.` : ''
  return `${approval.use_case_name}, set up by ${nameOf(approval.owner)}. ${starter}${retried}`
}

/** What happens next. Under today's rule a waiting request never expires, so it names no stop time and no backup. */
export function happensWords(approval: ApprovalView, canDecide: boolean): string {
  const who = canDecide ? 'you say yes' : 'an Approver says yes'
  const order = approval.steps.length > 1 ? ' It needs two Approvers, one after the other.' : ''
  return `Nothing is written until ${who}.${order} The request waits until someone decides. ${canDecide ? 'If you decline' : 'If an Approver declines'}, the run stops there.`
}

/** The reader's part: why they can decide, which of two yeses is theirs, or why they can't. */
export function yourPart(approval: ApprovalView, party: Party | null, nameOf: NameOf): string | null {
  const step = openStep(approval)
  if (!step) return null
  if (!approval.you_can_decide) return lockWords(approval.why_not, party)
  const before = approval.steps.filter((other) => other.index < step.index && other.status === 'approved')
  if (before.length > 0 && approval.steps.length === 2) {
    const said = andList(before.map((other) => (other.decided_by ? nameOf(other.decided_by) : 'Another Approver')))
    return `${said} said yes. Your yes is the second of two.`
  }
  return 'You can decide because you didn’t set this up or start this run.'
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
