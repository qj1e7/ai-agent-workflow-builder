import { newIdempotencyKey } from '../../api/idempotency'
import type { Latch } from '../../api/latch'

export interface StartOutcome {
  onSuccess?: (started: { readonly run_id: string }) => void
  onSettled?: () => void
}

type Start = (input: { useCaseId: string; idempotencyKey: string }, outcome: StartOutcome) => void

/** The platform does not merge two checks, so a second press before it answers is dropped here. */
export function pressCheckNow(latch: Latch, start: Start, useCaseId: string, open: (runId: string) => void): void {
  latch.run((settled) => start({ useCaseId, idempotencyKey: newIdempotencyKey() }, { onSuccess: (started) => open(started.run_id), onSettled: settled }))
}
