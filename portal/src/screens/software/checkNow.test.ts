import { describe, expect, it } from 'vitest'
import { createLatch } from '../../api/latch'
import { pressCheckNow, type StartOutcome } from './checkNow'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function harness() {
  const started: { useCaseId: string; idempotencyKey: string }[] = []
  const outcomes: StartOutcome[] = []
  const opened: string[] = []
  const latch = createLatch()
  const press = () =>
    pressCheckNow(
      latch,
      (input, outcome) => {
        started.push(input)
        outcomes.push(outcome)
      },
      'uc_watch',
      (runId) => opened.push(runId),
    )
  return { started, outcomes, opened, press }
}

describe('Check now', () => {
  it('starts one check for two presses in one tick, with a fresh key', () => {
    const h = harness()
    h.press()
    h.press()
    expect(h.started).toHaveLength(1)
    expect(h.started[0]?.useCaseId).toBe('uc_watch')
    expect(h.started[0]?.idempotencyKey).toMatch(UUID)
  })

  it('opens the new run’s page when the platform answers', () => {
    const h = harness()
    h.press()
    h.outcomes[0]?.onSuccess?.({ run_id: 'run_01' })
    h.outcomes[0]?.onSettled?.()
    expect(h.opened).toEqual(['run_01'])
  })

  it('lets the next press start another check with a new key once the platform answered, even with an error', () => {
    const h = harness()
    h.press()
    h.outcomes[0]?.onSettled?.()
    h.press()
    expect(h.started).toHaveLength(2)
    expect(h.started[1]?.idempotencyKey).not.toBe(h.started[0]?.idempotencyKey)
    expect(h.opened).toEqual([])
  })
})
