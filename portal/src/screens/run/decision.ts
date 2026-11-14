import { useState } from 'react'
import { useCacheScope, useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useCapabilities } from '../../api/plannerQueries'
import { isConflict, refusalOf, useDecide } from '../../api/queries'
import type { ApprovalStepView, ApprovalView, CapabilityView, DecisionIn, DecisionView, UseCaseView, Verdict } from '../../api/types'
import { cardsOf } from '../workflows/workflow'
import type { Declined } from './runModel'
import { andList, CONFLICT_WORDS, declinedOfSteps, lockWords, type Party } from './words'

export function openStep(approval: ApprovalView): ApprovalStepView | null {
  return approval.steps.find((step) => step.status === 'open') ?? null
}

/**
 * Where a request stands, from its steps: waiting at one step, or over. Only an open request takes a decision, so an expired,
 * cancelled or decided one says why instead of offering buttons.
 */
export type Standing =
  | { readonly is: 'open'; readonly step: number; readonly steps: number; readonly approvedBy: readonly string[] }
  | { readonly is: 'approved'; readonly by: readonly string[]; readonly at: string | null }
  | { readonly is: 'declined'; readonly record: Declined; readonly at: string | null }
  | { readonly is: 'expired' | 'cancelled' }

export function standingOf(steps: readonly ApprovalStepView[]): Standing {
  const declined = steps.find((step) => step.status === 'declined')
  if (declined) return { is: 'declined', record: declinedOfSteps(steps) ?? { by: declined.decided_by ?? '', approvedBy: [], reason: declined.reason ?? null }, at: declined.decided_at ?? null }
  if (steps.some((step) => step.status === 'expired')) return { is: 'expired' }
  if (steps.some((step) => step.status === 'cancelled')) return { is: 'cancelled' }
  const approved = steps.filter((step) => step.status === 'approved')
  const by = approved.flatMap((step) => (step.decided_by ? [step.decided_by] : []))
  const open = steps.find((step) => step.status === 'open' || step.status === 'waiting')
  if (open) return { is: 'open', step: open.index, steps: steps.length, approvedBy: by }
  return { is: 'approved', by, at: approved.at(-1)?.decided_at ?? null }
}

/** The steps with this person's recorded decision in, until the platform's next read shows it. */
export function stepsAfter(steps: readonly ApprovalStepView[], decision: DecisionView): readonly ApprovalStepView[] {
  if (steps.find((step) => step.index === decision.step)?.status !== 'open') return steps
  const status = decision.verdict === 'approve' ? ('approved' as const) : ('declined' as const)
  return steps.map((step) => (step.index === decision.step ? { ...step, status, decided_by: decision.by, decided_at: decision.at, reason: decision.reason ?? null } : step))
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

/**
 * What a run checks, and the registry entries that would check more of it. The first a workflow's agents use is what the run
 * checks: a release check also reads Jira, but only to find the tickets it raised.
 */
const CHECKS: readonly { readonly reads: string; readonly more: readonly string[] }[] = [
  { reads: 'github.releases', more: ['registries.check'] },
  { reads: 'jira.read', more: ['jira.find_by_update', 'jira.find_by_detail', 'jira.find_older'] },
]

/**
 * Not checked (spec 10.4), only from the run and the capability registry: the software the run couldn't read, then what the
 * platform can't yet check of what the run checks. An entry the registry says is Ready is never listed.
 */
export function notCheckedWords(unread: readonly string[], cards: readonly string[], capabilities: readonly CapabilityView[] | undefined): readonly string[] {
  const registry = capabilities ?? []
  const check = CHECKS.find(({ reads }) => registry.some((c) => c.id === reads && c.agents.some((card) => cards.includes(card))))
  const cant = registry.flatMap((c) => (check?.more.includes(c.id) && c.state !== 'ready' && c.cant ? [`The platform can’t yet ${c.cant.replaceAll("'", '’')}.`] : []))
  const read = unread.length > 0 ? [`${andList(unread)} couldn’t be read, so no ticket is proposed for ${unread.length === 1 ? 'it' : 'them'}.`] : []
  return [...read, ...cant]
}

/**
 * Not checked for a request, waiting or decided. Null until the registry has answered, so the section never grows under the
 * Approver's pointer. If the registry can't be read, only the run's own lines are given.
 */
export function useNotChecked(approval: ApprovalView | undefined, useCase: Pick<UseCaseView, 'template' | 'agents'> | undefined): readonly string[] | null {
  const capabilities = useCapabilities({ enabled: approval !== undefined })
  if (!approval) return []
  if (capabilities.isPending) return null
  return notCheckedWords(approval.not_checked, useCase ? cardsOf(useCase).map((card) => card.card_id) : [], capabilities.data?.capabilities)
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

/** Whether this person may say yes now: the platform says so, the request is open, and they haven't just decided it here. */
export function canDecideNow(approval: ApprovalView, decision: Pick<Decision, 'recorded' | 'steps'>): boolean {
  return approval.you_can_decide && standingOf(decision.steps ?? approval.steps).is === 'open' && decision.recorded === null
}

export interface Decision {
  readonly pending: Verdict | null
  /** The verdict the platform recorded for this person on this page. */
  readonly recorded: Verdict | null
  /** The record of the decline the platform recorded for this person on this page. */
  readonly declined: Declined | null
  /** The request's steps with that decision in, ahead of the next read. Null until this person decides here. */
  readonly steps: readonly ApprovalStepView[] | null
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
  const [sent, setSent] = useState<{ by: string; verdict: Verdict } | null>(null)
  const mine = sent !== null && sent.by === user

  function decide(choice: Choice): void {
    const body = decisionFor(approval, choice)
    if (!body || !approval) return
    latch.run((settled) => {
      setSent({ by: user, verdict: choice.verdict })
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
  const recorded = mine && mutation.isSuccess ? mutation.data.decision : null
  const steps = recorded && approval ? stepsAfter(approval.steps, recorded) : null
  return {
    pending: mine && mutation.isPending ? sent.verdict : null,
    recorded: recorded ? recorded.verdict : null,
    declined: recorded?.verdict === 'decline' && steps ? declinedOfSteps(steps) : null,
    steps,
    error,
    decide,
  }
}
