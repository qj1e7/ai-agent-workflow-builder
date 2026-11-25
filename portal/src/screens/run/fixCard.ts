import type { FixOffer, FixView } from '../../api/types'
import { fixEnd, type FixHandBack, type FixState } from './runModel'
import { fixWords } from './words'

/** Where a fix stands. The platform's state wins once it answers, the activity until then, and the deadline over both while nothing ended it. */
export type FixStage = FixView['state'] | 'ready'

export const ONLY_OPERATORS = 'An Operator can ask for a fix.'
export const OPERATOR_ANSWERS = 'An Operator answers this.'
/** The platform's words when fixes are off here (builder/fixes.py, OFF). Nobody needs a note about a feature that isn't there. */
export const FIX_OFF = 'Fix it for me is off here.'
export const HANDED_BACK_HEAD = "I couldn't fix this. Here's the cause and what I tried."
export const NEXT_STEP = 'Open the workflow and change it yourself, or report this to support.'

/** The platform's words for each reason a fix is handed back (HANDED_BACK in monitoring/fix_events.py). */
export const HAND_BACK_WORDS: Readonly<Record<FixHandBack, string>> = {
  no_cause: "The cause couldn't be confirmed.",
  no_progress: 'A round made no progress.',
  no_answer: "The Fix drafter didn't answer.",
  widened: 'The change went further than the failed part.',
  round_limit: 'I reached the limit of 3 rounds.',
  handoff_limit: 'I reached the limit of 12 hand-offs.',
  cost_limit: 'I reached the cost limit for one fix.',
  time_limit: 'I reached the time limit for one fix.',
  gave_up: 'I found no change that works.',
  not_replayed: "The practice systems couldn't replay the stop, so no fix could be proven.",
}
export const TIME_LIMIT = HAND_BACK_WORDS.time_limit

const STAGES: Readonly<Record<NonNullable<ReturnType<typeof fixEnd>> | 'drafting', FixStage>> = { drafting: 'drafting', proposed: 'ready', handed_back: 'handed_back' }

/** The fix's stage: 'ready' is a fix waiting for a yes, and the rest are the platform's own states. */
export function fixStageOf(fix: FixState | null, view: Pick<FixView, 'fix_id' | 'state'> | undefined, now: number): FixStage | null {
  if (fix === null) return null
  const own = view !== undefined && view.fix_id === fix.id ? view.state : null
  if (own === 'drafting' && now >= fix.endsBy) return 'handed_back'
  const stage = own ?? STAGES[fixEnd(fix, now) ?? 'drafting']
  return stage === 'waiting' ? 'ready' : stage
}

/** The one sentence under the stop. The platform's once it answers about this fix, and the activity's until then. */
export function fixLine(fix: FixState, view: Pick<FixView, 'fix_id' | 'state' | 'said'> | undefined, now: number): string {
  const own = view !== undefined && view.fix_id === fix.id ? view : null
  if (own === null || (own.state === 'drafting' && now >= fix.endsBy)) return fixWords(fix, now)
  return own.said
}

/** Why a fix was handed back, from the reason code the hand-back carried. The time limit when only the deadline passed. Null while the fix goes on. */
export function handedBackWords(fix: FixState, now: number): string | null {
  if (fixEnd(fix, now) !== 'handed_back') return null
  return fix.why === null ? TIME_LIMIT : HAND_BACK_WORDS[fix.why]
}

export type Ask = { readonly is: 'button' } | { readonly is: 'note'; readonly words: string }

const ASK_AGAIN: ReadonlySet<FixStage> = new Set(['declined', 'dropped'])

/**
 * What a stopped run offers about a fix, from the platform's own answer to whether one can start (the run's fix_offer). An
 * Operator gets the button when it can, and the platform's reason when it can't. An Approver reads why they can't ask, and
 * nothing when a fix couldn't start anyway. Nothing shows while a fix is under way or done, and again only after a no.
 */
export function askFix({ operator, next, offer, stage }: { operator: boolean; next: 'retry' | 'report' | undefined; offer: FixOffer | null | undefined; stage: FixStage | null }): Ask | null {
  if (next !== 'report' || offer === null || offer === undefined) return null
  if (stage !== null && !ASK_AGAIN.has(stage)) return null
  if (!offer.can) return operator && offer.why_not !== null && offer.why_not !== FIX_OFF ? { is: 'note', words: offer.why_not } : null
  return operator ? { is: 'button' } : { is: 'note', words: ONLY_OPERATORS }
}

/** Whether a fix has the stop's one main button: Fix it for me while offered, Turn back on for an Operator after the yes, Review the fix for an Approver who didn't ask. */
export function fixLeads({ ask, stage, view, operator, approverId }: { ask: Ask | null; stage: FixStage | null; view: Pick<FixView, 'can_turn_back_on' | 'asked_by'> | undefined; operator: boolean; approverId: string | null }): boolean {
  if (ask?.is === 'button') return true
  if (stage === 'approved') return operator && view?.can_turn_back_on === true
  return stage === 'ready' && approverId !== null && view !== undefined && view.asked_by !== approverId
}
