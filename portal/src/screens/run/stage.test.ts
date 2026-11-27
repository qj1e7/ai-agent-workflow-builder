import { describe, expect, it } from 'vitest'
import type { StepState } from '../../ui/StepLine'
import type { Station } from './runModel'
import { geometryOf, handoffsOf, MAX_STAGE_STEPS, stageOf, STAGE_STATE_WORDS } from './stage'

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

  it('draws the Planner thinking while a step is at work, and waiting while the gate waits', () => {
    expect(stageOf(line('done', 'now'))?.planner).toBe('thinking')
    expect(stageOf(line('done', 'done', 'wait'))?.planner).toBe('waiting')
  })

  it('draws the Planner with a mark on a stop, smiling once everything is done, and idle before it starts', () => {
    expect(stageOf(line('done', 'err'))?.planner).toBe('error')
    expect(stageOf(line('done', 'done', 'done', 'done'))?.planner).toBe('success')
    expect(stageOf(line('todo', 'todo'))?.planner).toBe('idle')
  })

  it('joins each reached step to the one before it, and leaves the rest dashed', () => {
    const wires = stageOf(line('done', 'done', 'now'))?.wires.filter((wire) => wire.from !== 'planner')
    expect(wires?.map((wire) => `${wire.id}:${wire.kind}`)).toEqual(['track:1:track', 'track:2:track', 'track:3:todo'])
  })

  it('hands off from the Planner to each agent step in violet, and to the gate in amber', () => {
    const wires = stageOf(line('done', 'done', 'wait'))?.wires.filter((wire) => wire.from === 'planner' && wire.kind !== 'todo')
    expect(wires?.map((wire) => `${wire.to}:${wire.kind}`)).toEqual(['1:ai', '2:gate'])
  })

  it('cuts the Planner wire to a step that stopped, and does not wire the Planner to its own face', () => {
    const stopped = stageOf(line('done', 'err'))
    expect(stopped?.wires.find((wire) => wire.id === 'plan:1')?.kind).toBe('cut')
    const picking = [station('trigger', 'done', 'started'), station('agent:0', 'now', 'agent', { id: 'planner', display: 'Planner' })]
    expect(stageOf(picking)?.wires.some((wire) => wire.from === 'planner')).toBe(false)
  })

  it('falls back to the plain step line over six steps', () => {
    const six = Array.from({ length: MAX_STAGE_STEPS }, (_, index) => station(`s${index}`, 'todo', 'started'))
    expect(stageOf(six)).not.toBeNull()
    expect(stageOf([...six, station('more', 'todo', 'started')])).toBeNull()
    expect(stageOf([])).toBeNull()
  })

  it('says each state in one word or two', () => {
    expect(STAGE_STATE_WORDS).toEqual({ todo: 'Not reached yet', now: 'At work', wait: 'Waits for approval', done: 'Done', err: 'Stopped', no: 'Declined', skip: 'Skipped' })
  })
})

describe('the hand-offs that glow', () => {
  it('plays every reached wire in order when the stage opens, each a little after the one before, in under five seconds', () => {
    const plays = handoffsOf(stageOf(line('done', 'done', 'wait'))!, null)
    expect(plays.map((play) => play.id)).toEqual(['track:1', 'plan:1', 'track:2', 'plan:2'])
    expect(plays.map((play) => play.delay)).toEqual([...plays.map((play) => play.delay)].sort((a, b) => a - b))
    expect(new Set(plays.map((play) => play.delay)).size).toBe(plays.length)
    expect(Math.max(...plays.map((play) => play.delay))).toBeLessThan(5)
  })

  it('after that, glows only into a step that just changed', () => {
    const plays = handoffsOf(stageOf(line('done', 'done', 'wait'))!, statesOf(line('done', 'now', 'todo')))
    expect(plays.map((play) => play.id)).toEqual(['track:2', 'plan:2'])
    expect(plays.every((play) => play.delay === 0)).toBe(true)
  })

  it('glows nothing when nothing changed, or when a step stopped', () => {
    const same = line('done', 'now')
    expect(handoffsOf(stageOf(same)!, statesOf(same))).toEqual([])
    expect(handoffsOf(stageOf(line('done', 'err'))!, statesOf(line('done', 'now')))).toEqual([])
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
