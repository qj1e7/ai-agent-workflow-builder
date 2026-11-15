import type { Latch } from '../../api/latch'
import { isOperator } from '../../api/me'
import type { Me, RunView } from '../../api/types'

export const TEST_AGAIN = 'Do a test run again'

/**
 * The workflow a declined test run may be tested again as, or null. Only an Operator starts runs, and with no AI model the new test
 * would stop at once, so then the next step is only said.
 */
export function testAgainOf(run: Pick<RunView, 'state' | 'test' | 'use_case_id'>, me: Me | undefined, modelOff: boolean): string | null {
  return run.state === 'rejected' && run.test && isOperator(me) && !modelOff ? run.use_case_id : null
}

interface StartOutcome {
  onSuccess?: (started: { readonly run_id: string }) => void
  onSettled?: () => void
}

export type TestStart = (input: { useCaseId: string; idempotencyKey: string; test: true }, outcome: StartOutcome) => void

/** Starts one new test run of the workflow however often it is pressed before the platform answers, then opens it. */
export function pressTestAgain(latch: Latch, start: TestStart, { useCaseId, idempotencyKey }: { useCaseId: string; idempotencyKey: string }, open: (runId: string) => void): void {
  latch.run((settled) => start({ useCaseId, idempotencyKey, test: true }, { onSuccess: (started) => open(started.run_id), onSettled: settled }))
}
