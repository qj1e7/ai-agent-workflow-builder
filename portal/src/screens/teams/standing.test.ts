import { describe, expect, it } from 'vitest'
import type { ApprovalStepView } from '../../api/types'
import { standingOf } from './standing'

const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id

function step(index: number, label: string, status: ApprovalStepView['status'], by?: string, at?: string): ApprovalStepView {
  return { index, label, status, decided_by: by ?? null, decided_at: at ?? null }
}

describe('where an approval stands', () => {
  it('waits for a decision and names the step that is open', () => {
    expect(standingOf([step(0, 'Team approver', 'open')], nameOf)).toEqual({
      kind: 'waiting',
      headline: 'Waiting for a decision',
      detail: 'Waiting for Team approver.',
    })
  })

  it('says who approved the earlier step while the next one is open', () => {
    const standing = standingOf(
      [step(0, 'First approver', 'approved', 'bob', '2026-11-03T08:10:00Z'), step(1, 'Second approver', 'open')],
      nameOf,
    )
    expect(standing.kind).toBe('waiting')
    expect(standing.detail).toBe('Step 1 of 2 approved by Bob. Waiting for Second approver.')
  })

  it('is approved by the one who approved', () => {
    const standing = standingOf([step(0, 'Team approver', 'approved', 'bob', '2026-11-03T08:10:00Z')], nameOf)
    expect(standing.kind).toBe('approved')
    expect(standing.headline).toBe('Approved by Bob')
    expect(standing.detail).toMatch(/^3 Nov, \d\d:\d\d$/)
  })

  it('names both Approvers once both steps are approved, and each only once', () => {
    const both = standingOf(
      [step(0, 'First', 'approved', 'bob', '2026-11-03T08:10:00Z'), step(1, 'Second', 'approved', 'carol', '2026-11-03T08:20:00Z')],
      nameOf,
    )
    expect(both.headline).toBe('Approved by Bob and Carol')
    const same = standingOf(
      [step(0, 'First', 'approved', 'bob', '2026-11-03T08:10:00Z'), step(1, 'Second', 'approved', 'bob', '2026-11-03T08:20:00Z')],
      nameOf,
    )
    expect(same.headline).toBe('Approved by Bob')
  })

  it('is declined by the one who declined, even when an earlier step was approved', () => {
    const standing = standingOf(
      [step(0, 'First', 'approved', 'bob', '2026-11-03T08:10:00Z'), step(1, 'Second', 'declined', 'carol', '2026-11-03T08:20:00Z')],
      nameOf,
    )
    expect(standing.kind).toBe('declined')
    expect(standing.headline).toBe('Declined by Carol')
  })

  it('still reads as waiting when there are no steps yet', () => {
    expect(standingOf([], nameOf)).toEqual({ kind: 'waiting', headline: 'Waiting for a decision', detail: null })
  })
})
