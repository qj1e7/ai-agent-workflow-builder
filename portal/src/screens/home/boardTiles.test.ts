import { describe, expect, it } from 'vitest'
import watchlist from '../../../../contracts/fixtures/builder/use-case.json'
import failure from '../../../../contracts/fixtures/runs/failure.json'
import success from '../../../../contracts/fixtures/runs/success.json'
import type { UseCaseView } from '../../api/types'
import { BOARD_SHOWN, boardOf, nextUp, stepsOfRun } from './boardTiles'

const NOW = new Date('2026-11-27T01:00:00Z')
const base = watchlist as unknown as UseCaseView

const made = (id: string, over: Partial<UseCaseView> = {}): UseCaseView => ({ ...base, use_case_id: id, name: `Workflow ${id}`, last_run: null, needs_you: null, next_run_at: null, ...over })

const ran = { run_id: 'run_01JB9', state: 'failed', at: '2026-11-27T00:00:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: true, you_can_decide: false, you_can_open: false, retryable: true, reason: null, stop: null, outcome: null } as UseCaseView['last_run']

describe('the Home board', () => {
  it('lists each workflow once, whatever its state, with the ones that need the person first', () => {
    const list = [made('a'), made('b', { needs_you: 'stopped' }), made('c', { state: 'paused' })]
    const { tiles, total } = boardOf(list, NOW)
    expect(tiles.map((tile) => tile.useCase.use_case_id)).toEqual(['b', 'a', 'c'])
    expect(total).toBe(3)
  })

  it('draws only as many tiles as it will read a last run for, and counts all of them', () => {
    const list = Array.from({ length: BOARD_SHOWN + 3 }, (_, index) => made(`w${String(index)}`))
    const { tiles, total } = boardOf(list, NOW)
    expect(tiles).toHaveLength(BOARD_SHOWN)
    expect(total).toBe(BOARD_SHOWN + 3)
  })

  it('names the next run only for a workflow that is on, so a pill is not said twice', () => {
    const { tiles } = boardOf([made('a', { state: 'paused' }), made('b', { state: 'draft' }), made('c', { next_run_at: '2026-11-30T01:00:00Z' })], NOW)
    expect(tiles.map((tile) => tile.next)).toEqual([null, null, expect.stringMatching(/Mon/)])
  })

  it('carries the id of the last run, and none before the first run', () => {
    const { tiles } = boardOf([made('a'), made('b', { last_run: ran })], NOW)
    expect(tiles.map((tile) => tile.lastRunId)).toEqual([null, 'run_01JB9'])
  })
})

describe('next up', () => {
  it('is the soonest next run among the workflows that are on', () => {
    const list = [made('a', { next_run_at: '2026-12-01T01:00:00Z' }), made('b', { next_run_at: '2026-11-28T01:00:00Z' }), made('c', { state: 'paused', next_run_at: '2026-11-27T05:00:00Z' })]
    expect(nextUp(list, NOW)?.name).toBe('Workflow b')
  })

  it('is nothing when no workflow has a next run', () => {
    expect(nextUp([made('a'), made('b', { state: 'paused' })], NOW)).toBeNull()
  })
})

describe('a tile’s last run as steps', () => {
  const states = (steps: ReturnType<typeof stepsOfRun>) => steps.map((step) => step.state)

  it('reads each step from the run’s own events, as the run page does', () => {
    const steps = stepsOfRun(success, 'run_01JB8', base, (id) => id)
    expect(steps.length).toBeGreaterThanOrEqual(3)
    expect(states(steps).at(-1)).toBe('done')
  })

  it('shows the step that stopped a stopped run, and the steps after it not reached', () => {
    const steps = stepsOfRun(failure, 'run_01JB9', base, (id) => id)
    expect(states(steps)).toContain('err')
    expect(states(steps).at(-1)).toBe('todo')
  })

  it('draws no steps from no events, so a tile never shows a made-up line', () => {
    expect(stepsOfRun([], 'run_x', base, (id) => id)).toEqual([])
  })
})
