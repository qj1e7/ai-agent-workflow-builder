import { useState } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isConflict, refusalOf, useDecide } from '../../api/queries'
import type { ApprovalStepView, ApprovalView, DecisionIn, DecisionView, Verdict } from '../../api/types'
import { starterName } from '../../api/labels'
import type { Declined } from './runModel'
import { andList, CONFLICT_WORDS, declinedOfSteps, lockWords, type NameOf, type Party } from './words'

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

/** What the person decides. Only a decline takes a reason, and it is optional (spec 10.4). */
export type Choice = { readonly verdict: 'approve' } | { readonly verdict: 'decline'; readonly reason: string | null }

export const APPROVE: Choice = { verdict: 'approve' }

/** A few quick reasons to decline, as the prototype offers them. The software check has its own. */
export function declineReasons(template: string | undefined): readonly string[] {
  return template === 'software_watchlist' ? ['Not this week', 'Wrong version', 'Needs testing first'] : ['Not needed this time', 'Something in it is wrong']
}

/** What to post, or null when the platform said this person may not decide or nothing is open. Never from the stream. */
export function decisionFor(approval: ApprovalView | undefined, choice: Choice): DecisionIn | null {
  if (!approval?.you_can_decide) return null
  const step = openStep(approval)
  if (!step) return null
  const body = { step: step.index, verdict: choice.verdict, digest: approval.digest }
  return choice.verdict === 'decline' && choice.reason ? { ...body, reason: choice.reason } : body
}

/** The record of a decline the platform just recorded, ahead of the run's own events: the steps as they were, with the decline in. */
export function declinedNow(steps: readonly ApprovalStepView[], decision: DecisionView): Declined | null {
  const decided = steps.map((step) => (step.index === decision.step ? { ...step, status: 'declined' as const, decided_by: decision.by, decided_at: decision.at, reason: decision.reason ?? null } : step))
  return declinedOfSteps(decided)
}

export interface Decision {
  readonly pending: Verdict | null
  /** The verdict the platform recorded for this person on this page. */
  readonly recorded: Verdict | null
  /** The record of the decline the platform recorded for this person on this page. */
  readonly declined: Declined | null
  readonly error: string | null
  decide(this: void, choice: Choice): void
}

/**
 * It posts only when the platform said this person may decide. A second press before the first answer is dropped.
 * A dev user switch starts clean, because it remembers who sent it.
 */
export function useDecision(approval: ApprovalView | undefined, party: Party | null, onRecorded?: (decision: DecisionView) => void): Decision {
  const mutation = useDecide(approval?.approval_id ?? '')
  const latch = useLatch()
  const user = useCacheScope()
  const errorWords = useErrorWords()
  const [sent, setSent] = useState<{ by: string; verdict: Verdict; steps: readonly ApprovalStepView[] } | null>(null)
  const mine = sent !== null && sent.by === user

  function decide(choice: Choice): void {
    const body = decisionFor(approval, choice)
    if (!body || !approval) return
    const { steps } = approval
    latch.run((settled) => {
      setSent({ by: user, verdict: choice.verdict, steps })
      mutation.mutate(body, {
        onSuccess: (answer) => onRecorded?.(answer.decision),
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
  const recorded = mine && mutation.isSuccess ? { decision: mutation.data.decision, steps: sent.steps } : null
  return {
    pending: mine && mutation.isPending ? sent.verdict : null,
    recorded: recorded ? recorded.decision.verdict : null,
    declined: recorded?.decision.verdict === 'decline' ? declinedNow(recorded.steps, recorded.decision) : null,
    error,
    decide,
  }
}
