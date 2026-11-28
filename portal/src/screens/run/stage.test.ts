import { describe, expect, it } from 'vitest'
import type { StepState } from '../../ui/StepLine'
import type { Station } from './runModel'
import { geometryOf, handoffsOf, MAX_STAGE_STEPS, plannerFaceOf, stageOf, stoppedAt, stopPointer } from './stage'

const agent = { id: 'version_checker', display: 'Version checker' }

function station(key: string, state: StepState, kind: 'started' | 'agent' | 'gate' | 'write', who: Station['agent'] = null): Station {
  const spot = kind === 'agent' ? ({ at: 'agent', index: 0 } as const) : ({ at: kind } as const)
  const icon = kind === 'gate' ? 'gate' : kind === 'write' ? 'write' : kind === 'agent' ? 'read' : 'schedule'
  return { key, spot, label: key, icon, agent: who, state, face: 'idle', under: null }
}

const line = (...states: StepState[]): Station[] => [
  station('trigger', states[0] ?? 'todo', 'started'),
  station('agent:0', states[1] ?? 'todo', 'agent', agent),
  station('gate', states[2] ?? 'todo', 'gate'),
  station('write', states[3] ?? 'todo', 'write'),
]

const statesOf = (stations: readonly Station[]) => Object.fromEntries(stations.map((s) => [s.key, s.state]))

describe('the stage from the run line', () => {
  it('puts a face on an agent step and the step icon on every other step', () => {
    const stage = stageOf(line('done', 'now', 'todo', 'todo'))
    expect(stage?.nodes.map((node) => node.picture)).toEqual(['icon', 'face', 'icon', 'icon'])
  })

  it('shows the icon for an agent step that has no agent yet', () => {
    const open = [station('trigger', 'done', 'started'), station('agent:0', 'todo', 'agent', null)]
    expect(stageOf(open)?.nodes[1]?.picture).toBe('icon')
  })

  it('joins each reached step to the one before it, and leaves the rest dashed', () => {
    const wires = stageOf(line('done', 'done', 'now'))?.wires.filter((wire) => wire.from !== 'planner')
    expect(wires?.map((wire) => `${wire.id}:${wire.kind}`)).toEqual(['track:1:track', 'track:2:track', 'track:3:todo'])
  })

  it('hands off from the Planner to each agent step in violet, and to the gate in amber', () => {
    const wires = stageOf(line('done', 'done', 'wait'))?.wires.filter((wire) => wire.from === 'planner' && wire.kind !== 'todo')
    expect(wires?.map((wire) => `${wire.to}:${wire.kind}`)).toEqual(['1:ai', '2:gate'])
  })

  it('keeps the Planner wire to a step that stopped violet, and does not wire the Planner to its own face', () => {
    const stopped = stageOf(line('done', 'err'))
    expect(stopped?.wires.find((wire) => wire.id === 'plan:1')?.kind).toBe('ai')
    const picking = [station('trigger', 'done', 'started'), station('agent:0', 'now', 'agent', { id: 'planner', display: 'Planner' })]
    expect(stageOf(picking)?.wires.some((wire) => wire.from === 'planner')).toBe(false)
  })

  it('falls back to the plain step line over six steps', () => {
    const six = Array.from({ length: MAX_STAGE_STEPS }, (_, index) => station(`s${index}`, 'todo', 'started'))
    expect(stageOf(six)).not.toBeNull()
    expect(stageOf([...six, station('more', 'todo', 'started')])).toBeNull()
    expect(stageOf([])).toBeNull()
  })
})

describe('the Planner face follows the run, not the steps', () => {
  it('works while the run goes, waits at the gate, smiles only when it succeeded, and frowns on a stop', () => {
    for (const state of ['pending', 'working', 'proposed', 'acting'] as const) expect(plannerFaceOf(state)).toBe('thinking')
    expect(plannerFaceOf('awaiting_approval')).toBe('waiting')
    expect(plannerFaceOf('succeeded')).toBe('success')
    expect(plannerFaceOf('failed')).toBe('error')
  })

  it('does not smile or frown on a run that was declined, expired, lost or skipped', () => {
    for (const state of ['rejected', 'expired', 'lost', 'skipped'] as const) expect(plannerFaceOf(state)).toBe('idle')
  })
})

describe('the hand-offs that glow', () => {
  it('plays every reached wire in order when the stage opens, each a little after the one before', () => {
    const plays = handoffsOf(stageOf(line('done', 'done', 'wait'))!, null)
    expect(plays.map((play) => play.id)).toEqual(['track:1', 'plan:1', 'track:2', 'plan:2'])
    expect(plays.map((play) => play.delay)).toEqual([...plays.map((play) => play.delay)].sort((a, b) => a - b))
    expect(new Set(plays.map((play) => play.delay)).size).toBe(plays.length)
  })

  it('opens in under five seconds even for six steps', () => {
    const six = [
      station('trigger', 'done', 'started'),
      { ...station('agent:0', 'done', 'agent', agent), key: 'agent:0' },
      { ...station('agent:1', 'done', 'agent', agent), key: 'agent:1' },
      { ...station('agent:2', 'done', 'agent', agent), key: 'agent:2' },
      station('gate', 'done', 'gate'),
      station('write', 'done', 'write'),
    ]
    const plays = handoffsOf(stageOf(six)!, null)
    expect(plays).toHaveLength(9)
    expect(Math.max(...plays.map((play) => play.delay)) + 0.8).toBeLessThanOrEqual(5)
    expect(new Set(plays.map((play) => play.delay)).size).toBe(plays.length)
  })

  it('opens a stopped run with the work flowing into the stop', () => {
    const plays = handoffsOf(stageOf(line('done', 'err'))!, null)
    expect(plays.map((play) => play.id)).toEqual(['track:1', 'plan:1'])
  })

  it('opens a declined run with the work flowing into the gate, as the sketch does', () => {
    const plays = handoffsOf(stageOf(line('done', 'done', 'no'))!, null)
    expect(plays.map((play) => play.id)).toEqual(['track:1', 'plan:1', 'track:2', 'plan:2'])
    expect(plays.every((play) => play.delay >= 0)).toBe(true)
  })

  it('after that, glows into each step that changed, so a retry flows into the step again', () => {
    const plays = handoffsOf(stageOf(line('done', 'done', 'wait'))!, statesOf(line('done', 'now', 'todo')))
    expect(plays.map((play) => play.id)).toEqual(['track:1', 'plan:1', 'track:2', 'plan:2'])
    expect(plays.every((play) => play.delay === 0)).toBe(true)
    expect(handoffsOf(stageOf(line('done', 'now'))!, statesOf(line('done', 'err'))).map((play) => play.id)).toEqual(['track:1', 'plan:1'])
  })

  it('glows nothing when nothing changed, and nothing into a stop or a decline that just happened', () => {
    const same = line('done', 'now')
    expect(handoffsOf(stageOf(same)!, statesOf(same))).toEqual([])
    expect(handoffsOf(stageOf(line('done', 'err'))!, statesOf(line('done', 'now')))).toEqual([])
    expect(handoffsOf(stageOf(line('done', 'done', 'no'))!, statesOf(line('done', 'done', 'wait')))).toEqual([])
  })
})

describe('where the stop is', () => {
  it("is the middle of the stopped step's column, as a share of the stage's width, for the card that points at it", () => {
    expect(stoppedAt(line('done', 'err', 'todo', 'todo'))).toBeCloseTo(0.375, 5)
    expect(stoppedAt(line('err', 'todo', 'todo', 'todo'))).toBeCloseTo(0.125, 5)
  })

  it('is nothing when no step stopped, or when the stage is not drawn', () => {
    expect(stoppedAt(line('done', 'done', 'no', 'skip'))).toBeNull()
    expect(stoppedAt(line('done', 'now'))).toBeNull()
    const long = Array.from({ length: MAX_STAGE_STEPS + 1 }, (_, i) => station(`s${i}`, i === 2 ? 'err' : 'done', 'agent', agent))
    expect(stoppedAt(long)).toBeNull()
  })
})

describe('where each part sits', () => {
  it('centres each column, so the wires meet the steps', () => {
    const geometry = geometryOf(5, 1000)
    expect(geometry.columns).toEqual([100, 300, 500, 700, 900])
    expect(geometry.planner.x).toBe(500)
  })

  it('shrinks the circles in a narrow stage, never below 52', () => {
    expect(geometryOf(5, 1000).node).toBe(84)
    expect(geometryOf(6, 560).node).toBeLessThan(84)
    expect(geometryOf(6, 200).node).toBe(52)
  })

  it('draws a track between the edges of two circles on their centre line', () => {
    const geometry = geometryOf(5, 1000)
    expect(geometry.track(1)).toBe(`M${100 + geometry.node / 2} ${geometry.centreY}H${300 - geometry.node / 2}`)
  })
})
