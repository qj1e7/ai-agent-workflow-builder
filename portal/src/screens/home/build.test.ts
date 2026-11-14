import created from '@contracts/fixtures/builder/agent-use-case.off.created.json'
import draft from '@contracts/fixtures/builder/use-case.draft.json'
import success from '@contracts/fixtures/runs/success.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import { describe, expect, it } from 'vitest'
import type { BuildLineView, N8nBlockView, UseCaseView } from '../../api/types'
import { emptyModel, foldWire, stationsOf, type PlanBlock, type RunModel } from '../run/runModel'
import { buildLine, buildStage, canvasOf, checksOf, draftPill, lineTimes, notesOf, replayAt, statusOf, testStatus, testStep } from './build'

const LOG = created.build_log as BuildLineView[]
const BLOCKS = created.blocks as N8nBlockView[]
const PLAN: PlanBlock[] = (draft as UseCaseView).plan.map(({ key, name, kind }) => ({ key, name, kind }))
const START = Date.parse('2026-11-14T03:00:00Z')

const events = (raw: readonly { run_id: string; seq: number }[], upTo = Infinity): RunModel => foldWire(emptyModel, raw.filter((item) => item.seq <= upTo), raw[0]?.run_id ?? '')

const ended = (model: RunModel, outcome: 'test_passed' | 'nothing_to_write'): RunModel =>
  foldWire(model, [{ run_id: 'run_01JB8', seq: model.seq + 1, ts: '2026-11-14T03:00:09Z', actor: { kind: 'platform', id: 'platform', display: 'Platform' }, summary: '', kind: 'run_succeeded', data: { outcome } }], 'run_01JB8')

/** The success fixture through the agents' work, before any proposal or yes: where a test run ends before it stops at the gate. */
const WORKING = events(success, 5)
const PROPOSED = events(success, 8)
const PASSED = ended(PROPOSED, 'test_passed')
const NOTHING_NEW = ended(WORKING, 'nothing_to_write')
const STOPPED = events(failure)
const DECLINED = events(rejected)

describe('the build log, replayed in order with its real gaps', () => {
  it('shows each line the sketch’s step after the one before, or after its real gap when that is longer', () => {
    const log: BuildLineView[] = [
      { at: '2026-11-02T01:00:00Z', kind: 'status', text: 'Adding blocks in n8n…' },
      { at: '2026-11-02T01:00:00.040Z', kind: 'check', text: 'The blocks fit together.' },
      { at: '2026-11-02T01:00:01.040Z', kind: 'status', text: 'Saved as a draft in n8n.' },
    ]
    expect(lineTimes(log, START, 320)).toEqual([START, START + 320, START + 1320])
  })

  it('shows every line at once with no motion', () => {
    expect(lineTimes(LOG, START, 0)).toEqual(LOG.map(() => START))
    expect(replayAt(LOG, START, 0, START)).toEqual({ lines: LOG, done: true, next: null })
  })

  it('shows only the lines whose time has come, and says when the next one is due', () => {
    const half = replayAt(LOG, START, 320, START + 330)
    expect(half.lines.map((line) => line.text)).toEqual(['Adding blocks in n8n…', 'The blocks fit together.'])
    expect(half.done).toBe(false)
    expect(half.next).toBe(START + 640)
    expect(replayAt(LOG, START, 320, START + 10_000).done).toBe(true)
  })
})

describe('where the set-up stands, from the replay, the test run’s events and the workflow', () => {
  it('lays out, waits for a test run to exist, tests, then is ready, or back to a draft when the test stopped, and is on only once the platform says so', () => {
    expect(buildStage(false, false, null, 'draft')).toEqual({ kind: 'laying_out' })
    expect(buildStage(true, false, null, 'draft'), 'no test run is claimed before the platform names one').toEqual({ kind: 'saved' })
    expect(buildStage(true, true, null, 'draft')).toEqual({ kind: 'testing' })
    expect(buildStage(true, true, WORKING.phase, 'draft')).toEqual({ kind: 'testing' })
    expect(buildStage(true, true, PASSED.phase, 'draft')).toEqual({ kind: 'passed' })
    expect(buildStage(true, true, NOTHING_NEW.phase, 'draft'), 'a test with nothing new to write still ran end to end').toEqual({ kind: 'passed' })
    expect(buildStage(true, true, STOPPED.phase, 'draft')).toEqual({ kind: 'stopped' })
    expect(buildStage(true, true, PASSED.phase, undefined), 'not on before the workflow is read').toEqual({ kind: 'passed' })
    expect(buildStage(true, true, PASSED.phase, 'on')).toEqual({ kind: 'on' })
  })

  it('has the sketch’s pill for each stage', () => {
    const pills = (['laying_out', 'saved', 'testing', 'passed', 'stopped', 'on'] as const).map((kind) => draftPill({ kind }).label)
    expect(pills).toEqual(['Building', 'Building', 'Building', 'Ready', 'Draft', 'On'])
  })
})

describe('starting the test run, once', () => {
  const held = { testRunId: null, testKey: 'k1', testAsked: null }

  it('starts it once the log has replayed and the platform says the workflow is a draft', () => {
    expect(testStep(held, false, 'draft')).toBe('wait')
    expect(testStep(held, true, undefined), 'not before the workflow is read').toBe('wait')
    expect(testStep(held, true, 'draft')).toBe('start')
    expect(testStep(held, true, 'on'), 'never for a workflow that is on').toBe('none')
    expect(testStep(undefined, true, 'draft'), 'never without the set-up it belongs to').toBe('none')
  })

  it('asks once in a card, asks again with the same key in a card drawn again, which reaches the same run, and Test again asks with a new key', () => {
    expect(testStep({ ...held, testAsked: 'k1' }, true, 'draft', true), 'once asked here, the answer or its problem is waited for').toBe('none')
    expect(testStep({ ...held, testAsked: 'k1' }, true, 'draft', false), 'a card drawn again before the run was named asks again with the same key').toBe('start')
    expect(testStep({ ...held, testKey: 'k2', testAsked: 'k1' }, true, 'draft', true)).toBe('start')
    expect(testStep({ ...held, testRunId: 'run_1' }, true, 'draft'), 'a run the platform named is followed, not started').toBe('none')
  })
})

describe('the build panel’s status line and checks', () => {
  const inN8n = { inN8n: true, version: 1 }

  it('says what the builder is doing, from the log, then the test run, then what the platform says', () => {
    expect(statusOf({ kind: 'laying_out' }, [], inN8n)).toBe('Starting…')
    expect(statusOf({ kind: 'laying_out' }, LOG.slice(0, 3), inN8n)).toBe('Safety checker is checking the write…')
    expect(statusOf({ kind: 'saved' }, LOG, inN8n), 'until the platform names a test run, the last line of the log stands').toBe('Saved as a draft in n8n.')
    expect(statusOf({ kind: 'testing' }, LOG, inN8n)).toBe('Test run…')
    expect(statusOf({ kind: 'passed' }, LOG, inN8n)).toBe('Saved as a draft in n8n.')
    expect(statusOf({ kind: 'on' }, LOG, inN8n)).toBe('On. Version 1, published in n8n.')
  })

  it('never says n8n when the platform did not lay the workflow out there', () => {
    const shared = { inN8n: false, version: 1 }
    expect(statusOf({ kind: 'passed' }, [], shared)).toBe('Saved as a draft.')
    expect(statusOf({ kind: 'on' }, [], shared)).toBe('On. Version 1.')
  })

  it('lists the checks that passed, then how the test run went, in the run’s own words', () => {
    expect(checksOf(LOG.slice(0, 2), null)).toEqual([{ ok: true, text: 'The blocks fit together.' }])
    expect(checksOf(LOG, testStatus(PASSED))).toEqual([
      { ok: true, text: 'The blocks fit together.' },
      { ok: true, text: 'Every write waits for a yes.' },
      { ok: true, text: 'Test run passed up to the yes. Nothing was written.' },
    ])
    expect(testStatus(STOPPED)).toEqual({ ok: false, text: 'The test run stopped. An agent could not finish its work.' })
    expect(testStatus(DECLINED)?.text, 'words that end a sentence get no second full stop').toMatch(/[^.]\.$/)
    expect(testStatus(WORKING), 'nothing is said while it runs').toBeNull()
  })

  it('gives the card the safety checker’s note once its line has shown', () => {
    expect(notesOf(LOG.slice(0, 3))).toEqual([])
    expect(notesOf(LOG)).toEqual(['Added a yes before the ticket.'])
  })
})

describe('the canvas, drawn from the blocks and moved only by the test run’s events', () => {
  const laid = { laid: true, yes: true }

  it('hides every block until the log says they were added, and the yes until the safety checker’s note', () => {
    expect(Object.values(canvasOf(BLOCKS, LOG, { laid: false, yes: false }, null, false).nodes).every((state) => state === 'off')).toBe(true)
    const before = canvasOf(BLOCKS, LOG, { laid: true, yes: false }, null, false)
    expect(before.nodes['Ask for a yes']).toBe('off')
    expect(before.nodes['Read release']).toBe('idle')
    expect(before.edges['Newer?->Ask for a yes']).toBe('off')
    expect(canvasOf(BLOCKS, LOG, laid, null, false).nodes['Ask for a yes'], 'the yes the safety checker added is ringed').toBe('added')
  })

  it('lights the entry the test run came in by, and the agents’ blocks while they work, never the schedule', () => {
    const working = canvasOf(BLOCKS, LOG, laid, WORKING, false)
    expect(working.nodes['Start from the Portal']).toBe('ok')
    expect(working.nodes['Mon 8:00']).toBe('idle')
    expect(working.nodes['Read release']).toBe('now')
    expect(working.edges['Start from the Portal->Read release']).toBe('flow')
    expect(working.edges['Mon 8:00->Read release']).toBe('idle')
  })

  it('ticks the blocks a passed test reached, and leaves the yes and the write as they were, since a test asks nobody and writes nothing', () => {
    const passed = canvasOf(BLOCKS, LOG, laid, PASSED, false)
    expect(passed.nodes['Read release']).toBe('ok')
    expect(passed.nodes['Compare']).toBe('ok')
    expect(passed.nodes['Newer?']).toBe('ok')
    expect(passed.nodes['Ask for a yes']).toBe('added')
    expect(passed.nodes['Create ticket']).toBe('idle')
    expect(passed.edges['Read release->Compare']).toBe('ok')
    expect(passed.edges['Newer?->Ask for a yes']).toBe('idle')
    const nothing = canvasOf(BLOCKS, LOG, laid, NOTHING_NEW, false)
    expect(nothing.nodes['Nothing to change']).toBe('ok')
    expect(nothing.edges['Newer?->Nothing to change']).toBe('ok')
  })

  it('drops the safety ring once the workflow is on', () => {
    expect(canvasOf(BLOCKS, LOG, laid, PASSED, true).nodes['Ask for a yes']).toBe('idle')
  })
})

describe('the card’s line while it builds', () => {
  const stations = (model: RunModel) => stationsOf(model, PLAN, 'Mon 8:00')

  it('hides every step until the blocks are added, then the yes until the note, with nothing ticked before the test', () => {
    expect(buildLine(stations(emptyModel), LOG, { laid: false, yes: false }, false, false).hidden).toEqual(new Set(['trigger', 'agent:0', 'gate', 'write']))
    const laid = buildLine(stations(emptyModel), LOG, { laid: true, yes: false }, false, false)
    expect(laid.hidden).toEqual(new Set(['gate']))
    expect(laid.stations.map((station) => station.state)).toEqual(['todo', 'todo', 'todo', 'todo'])
    expect(laid.stations[0]?.icon, 'the line starts at the schedule').toBe('schedule')
    expect(buildLine(stations(emptyModel), LOG, { laid: true, yes: true }, false, false).added).toBe('gate')
    expect(buildLine(stations(emptyModel), [], { laid: true, yes: true }, false, false).added, 'no ring when the safety checker added nothing').toBeNull()
  })

  it('follows the test run’s states, and drops the ring once on', () => {
    const passed = buildLine(stations(PASSED), LOG, { laid: true, yes: true }, true, false)
    expect(passed.stations.map((station) => station.state)).toEqual(['done', 'done', 'skip', 'skip'])
    expect(buildLine(stations(PASSED), LOG, { laid: true, yes: true }, true, true).added).toBeNull()
  })
})
