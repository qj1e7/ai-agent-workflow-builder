import { describe, expect, it } from 'vitest'
import type { RunView } from '../../api/types'
import type { DecisionPanel } from './decisionState'
import { ticketStatus } from './ticketStatus'

const open: DecisionPanel = { kind: 'cannot_decide', refusal: 'own_work', words: '', hint: null }
const approved: DecisionPanel = { kind: 'decided', verdict: 'approve', by: 'bob', at: '2026-11-03T02:20:23Z' }
const declined: DecisionPanel = { kind: 'decided', verdict: 'decline', by: 'bob', at: '2026-11-03T02:20:23Z' }

function succeeded(...keys: string[]): RunView {
  return {
    run_id: 'run_1',
    use_case_id: 'uc',
    use_case_name: 'Name',
    use_case_version: 1,
    started_by: 'alice',
    trigger: 'person',
    started_at: '2026-11-03T02:14:00Z',
    updated_at: '2026-11-03T02:20:26Z',
    last_seq: 23,
    events_url: '/e',
    state: 'succeeded',
    outcome: 'written',
    written: keys.map((key) => ({ connector: 'jira', operation: 'create_ticket', external_reference: key, approved_by: ['bob'] })),
  }
}

describe('what the ticket says it is', () => {
  it('is a draft until someone decides', () => {
    expect(ticketStatus(open, undefined)).toEqual({ kind: 'draft' })
  })

  it('is being written once approved, then carries the ticket key when the run has written it', () => {
    expect(ticketStatus(approved, undefined)).toEqual({ kind: 'writing' })
    expect(ticketStatus(approved, succeeded('MOCK-142'))).toEqual({ kind: 'written', key: 'MOCK-142' })
  })

  it('gives each ticket of a check its own key, in the order they were proposed', () => {
    const run = succeeded('MOCK-143', 'MOCK-144', 'MOCK-145')
    expect([0, 1, 2].map((index) => ticketStatus(approved, run, index))).toEqual([
      { kind: 'written', key: 'MOCK-143' },
      { kind: 'written', key: 'MOCK-144' },
      { kind: 'written', key: 'MOCK-145' },
    ])
  })

  it('is declined and never written after a decline, whatever the run shows', () => {
    expect(ticketStatus(declined, succeeded('MOCK-142'))).toEqual({ kind: 'declined' })
  })
})
