import type { FixView } from '../../api/types'
import { fixEnd, type FixState } from './runModel'
import { fixWords } from './words'

/** Where a fix stands. The platform's state wins once it answers, the activity until then, and the deadline over both while nothing ended it. */
export type FixStage = FixView['state']

export const ONLY_OPERATORS = 'An Operator can ask for a fix.'
/** The platform's own words for a start refused because no model is connected (builder/fixes.py, NO_MODEL). */
export const NO_AI_MODEL = 'Fix it for me needs an AI model, and none is connected yet.'
/** The platform's words for a hand-back at the deadline (HANDED_BACK["time_limit"] in monitoring/fix_events.py). */
export const TIME_LIMIT = 'I reached the time limit for one fix.'
export const HANDED_BACK_HEAD = "I couldn't fix this. Here's the cause and what I tried."
export const NEXT_STEP = 'Open the workflow and change it yourself, or report this to support.'

const STAGES: Readonly<Record<NonNullable<ReturnType<typeof fixEnd>> | 'drafting', FixStage>> = { drafting: 'drafting', proposed: 'waiting', handed_back: 'handed_back' }

/** Asks for the fix's stage: 'ready' is a fix waiting for a yes, and the rest are the platform's own states. */
export function fixStageOf(fix: FixState | null, view: Pick<FixView, 'fix_id' | 'state'> | undefined, now: number): FixStage | 'ready' | null {
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

/** Why a fix was handed back, in the platform's sentence without its heading and its closing line. Null while the fix goes on. */
export function handedBackWords(fix: FixState, now: number): string | null {
  if (fixEnd(fix, now) !== 'handed_back') return null
  if (fix.back === null) return TIME_LIMIT
  return fix.back.replace(/^I couldn't fix this\.\s*/, '').replace(/\s*Nothing was changed\.$/, '') || null
}

export type Ask = { readonly is: 'button' } | { readonly is: 'note'; readonly words: string }

const ASK_AGAIN: ReadonlySet<FixStage | 'ready'> = new Set(['handed_back', 'declined', 'dropped', 'test_failed'])

/**
 * What a stopped run offers about a fix. An Operator gets the button on a stop that a retry won't fix, and everyone else reads why
 * not. Nothing shows while a fix is under way or done, and a button never shows that the platform would refuse for a reason the
 * page already knows.
 */
export function askFix({ operator, next, stage, modelOff }: { operator: boolean; next: 'retry' | 'report' | undefined; stage: FixStage | 'ready' | null; modelOff: boolean }): Ask | null {
  if (next !== 'report') return null
  if (stage !== null && !ASK_AGAIN.has(stage)) return null
  if (!operator) return { is: 'note', words: ONLY_OPERATORS }
  return modelOff ? { is: 'note', words: NO_AI_MODEL } : { is: 'button' }
}
