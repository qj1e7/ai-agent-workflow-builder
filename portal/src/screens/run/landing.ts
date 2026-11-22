import type { RunState } from './words'

/** Where a run page opens: on a decision that waits for a yes, or at its top with a stop or a past decision to read. */
export type Landing = 'decide' | 'read'

export function landingOf(state: RunState, fromApproval: boolean): Landing | null {
  if (state === 'awaiting_approval') return 'decide'
  return fromApproval || state === 'failed' || state === 'rejected' ? 'read' : null
}

/** A decision that waits is always brought in from its top. One to read only when it is off screen, so the title, the state and the steps stay in view. */
export function scrollsToDecision(landing: Landing, decision: { readonly top: number; readonly bottom: number }, windowHeight: number): boolean {
  return landing === 'decide' || decision.top >= windowHeight || decision.bottom <= 0
}
