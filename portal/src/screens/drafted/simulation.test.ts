import { describe, expect, it } from 'vitest'
import ready from '../../../../contracts/fixtures/builder/drafted.ready.json'
import simulated from '../../../../contracts/fixtures/builder/drafted.simulated.json'
import simulating from '../../../../contracts/fixtures/builder/drafted.simulating.json'
import { stillMoving } from '../../api/draftedQueries'
import type { SimulationView, DraftedWorkflowView, SimulatedCaseView } from '../../api/types'
import { caseLimitWords, casesInOrder, KIND_WORDS, simulationLead, VERDICT_WORDS } from './simulation'

const done = (simulated as DraftedWorkflowView).simulation as SimulationView
const one = (kind: SimulatedCaseView['kind'], verdict: SimulatedCaseView['verdict']): SimulatedCaseView => ({ kind, verdict, expected: 'e', happened: 'h', note: null })

describe('simulation words (ADR 0054, PR 7)', () => {
  it('leads with how many cases were tried on practice systems and how many passed, as the ADR words it', () => {
    expect(simulationLead({ ...done, tried: 6, passed: 5 })).toBe('Tried 6 cases on practice systems: 5 passed.')
    expect(simulationLead({ ...done, tried: 1, passed: 1 })).toBe('Tried 1 case on practice systems: 1 passed.')
  })

  it('never counts a case no block could play: with none tried, it says so', () => {
    expect(simulationLead({ ...done, tried: 0, passed: 0, cases: [one('timeout', 'not_tried')] })).toBe('No case could be tried on practice systems.')
  })

  it('has a lead only once there is a result', () => {
    expect(simulationLead({ ...done, state: 'running' })).toBeNull()
    expect(simulationLead({ ...done, state: 'unavailable' })).toBeNull()
  })

  it('puts what failed first, then what was not tried, then what passed', () => {
    const cases = [one('happy_path', 'passed'), one('timeout', 'not_tried'), one('odd_data', 'failed'), one('nothing_new', 'passed')]
    expect(casesInOrder(cases).map((c) => c.kind)).toEqual(['odd_data', 'timeout', 'happy_path', 'nothing_new'])
  })

  it('names each kind and verdict in the glossary’s words', () => {
    expect(Object.values(KIND_WORDS)).toEqual(['Happy path', 'Nothing new', 'Source not found', 'Timeout', 'Approver says no', 'Odd data'])
    expect(VERDICT_WORDS).toEqual({ passed: 'Passed', failed: 'Failed', not_tried: 'Not tried' })
  })

  it('states each case’s time limit from the platform’s own number', () => {
    expect(caseLimitWords(120)).toBe('Each case can take up to 2 minutes.')
    expect(caseLimitWords(90)).toBe('Each case can take up to 90 seconds.')
  })

  it('reads the drafted workflow again while it is tried on practice systems, and stops once there is a result', () => {
    expect(stillMoving(simulating as DraftedWorkflowView)).toBe(true)
    expect(stillMoving(simulated as DraftedWorkflowView)).toBe(false)
    expect(stillMoving(ready as DraftedWorkflowView)).toBe(false)
  })
})
