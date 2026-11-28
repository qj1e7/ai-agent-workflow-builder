import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it } from 'vitest'
import type { UseCaseView } from '../../api/types'
import { flowOf, flowKeyOf, ranWords } from './flow'

const UC = useCase as unknown as UseCaseView
const NOW = new Date('2026-11-04T15:00:00+08:00')
const TODAY = '2026-11-04T00:00:00Z'
const run = (events: readonly unknown[]) => ({ runId: (events[0] as { run_id: string }).run_id, events, startedAt: TODAY })
const states = (events: readonly unknown[] | null) => flowOf(UC, events ? run(events) : null, NOW).steps.map((step) => step.state)

describe('the flow of a workflow with no run', () => {
  const flow = flowOf(UC, null, NOW)

  it('draws the designed steps with a tag under each, and no state, key, note or time', () => {
    expect(flow.steps.length).toBe(4)
    expect(flow.steps.map((step) => step.state)).toEqual([null, null, null, null])
    expect(flow.steps.map((step) => step.tag)).toEqual(['No system access', 'Reads only', 'Waits for approval', 'Writes after approval'])
    expect(flow.note).toBeNull()
    expect(flow.ranWhen).toBeNull()
    expect(flowKeyOf(flow)).toEqual([])
  })
})

describe('the flow of the latest run', () => {
  it("colours each box by the step the run reached, and keeps the steps' own names and tags", () => {
    expect(states(success)).toEqual(['done', 'done', 'done', 'done'])
    expect(flowOf(UC, run(success), NOW).steps[1]?.tag).toBe('Reads only')
  })

  it('says where a stopped run stopped, with the reason, under that step only', () => {
    const flow = flowOf(UC, run(failure), NOW)
    const at = flow.steps.findIndex((step) => step.state === 'err')
    expect(at).toBeGreaterThan(0)
    expect(flow.note).toMatchObject({ key: flow.steps[at]?.key, tone: 'err' })
    expect(flow.note?.text.length).toBeGreaterThan(0)
    const said = flowOf(UC, { ...run(failure), stage: { state: 'failed', count: 0, tickets: true, approvedBy: [], declinedBy: null, whyStopped: 'An agent could not finish its work.', test: false } }, NOW)
    expect(said.note?.text).toBe('An agent could not finish its work')
    expect(flowKeyOf(flow)).toContain('err')
  })

  it('says a run waits for approval under the gate, in the words the app has', () => {
    const flow = flowOf(UC, run(success.filter((event) => event.seq <= 15)), NOW)
    expect(flow.steps.map((step) => step.state)).toEqual(['done', 'done', 'wait', 'todo'])
    expect(flow.note).toEqual({ key: flow.steps[2]?.key, tone: 'wait', text: 'Waiting for approval' })
  })

  it('lists in the key only the states on the boxes, in a fixed order', () => {
    expect(flowKeyOf(flowOf(UC, run(success.filter((event) => event.seq <= 15)), NOW))).toEqual(['done', 'wait', 'todo'])
  })

  it('names the run by the time it started', () => {
    expect(ranWords('2026-11-04T00:00:00Z', NOW)).toBe('with today’s 8:00 run')
    expect(ranWords('2026-11-02T00:00:00Z', NOW)).toBe('with the Mon 2 Nov run')
  })
})
