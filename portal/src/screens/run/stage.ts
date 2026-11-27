import type { StepIcon, StepState } from '../../ui/StepLine'
import type { AgentRef, FaceState, Station, Under } from './runModel'

/** The stage is drawn for one line of up to this many steps. A longer line falls back to the plain step line (ADR 0052). */
export const MAX_STAGE_STEPS = 6

/** What each state says under its step. The stage's key in the sketch, so no colour stands alone. */
export const STAGE_STATE_WORDS: Readonly<Record<StepState, string>> = {
  todo: 'Not reached yet',
  now: 'At work',
  wait: 'Waits for approval',
  done: 'Done',
  err: 'Stopped',
  no: 'Declined',
  skip: 'Skipped',
}

/** A link takes the state of the step it leads into: solid once done, dashes into the step at work or the gate that waits, red into a stop. */
export type Link = 'solid' | 'flow' | 'wait' | 'stop' | 'dead' | 'todo'

export const LINK_INTO: Readonly<Record<StepState, Link>> = {
  todo: 'todo',
  now: 'flow',
  wait: 'wait',
  done: 'solid',
  err: 'stop',
  no: 'solid',
  skip: 'dead',
}

/** A step the run has reached: at work, waiting, done, stopped or declined. A skipped step was never reached. */
const REACHED: ReadonlySet<StepState> = new Set(['now', 'wait', 'done', 'err', 'no'])
export const reached = (state: StepState): boolean => REACHED.has(state)

/**
 * A wire: the track between two steps, the Planner's hand-off to an agent (violet) or to the gate (amber), or the Planner's wire to a
 * step that stopped, cut. A wire to a step not reached is dashed.
 */
export type WireKind = 'track' | 'ai' | 'gate' | 'cut' | 'todo'

export interface Wire {
  /** "track:2" joins step 1 to step 2. "plan:2" is the Planner's wire to step 2. */
  readonly id: string
  readonly kind: WireKind
  readonly from: 'planner' | number
  readonly to: number
}

export interface StageNode {
  readonly key: string
  readonly label: string
  readonly state: StepState
  /** An agent's face, or the step's icon when no agent is at the step. */
  readonly picture: 'face' | 'icon'
  readonly agent: AgentRef | null
  readonly face: FaceState
  readonly icon: StepIcon
  readonly gate: boolean
  readonly under: Under | null
}

export interface StageModel {
  readonly planner: FaceState
  readonly nodes: readonly StageNode[]
  readonly wires: readonly Wire[]
}

/** The Planner's face follows the run: it looks up with a clock while the gate waits, and frowns where a step stopped. */
function plannerFaceOf(stations: readonly Station[]): FaceState {
  const has = (state: StepState) => stations.some((station) => station.state === state)
  if (has('err')) return 'error'
  if (has('wait')) return 'waiting'
  if (has('now')) return 'thinking'
  if (has('todo') || !has('done')) return 'idle'
  return 'success'
}

function wireOf(station: Station, index: number): Wire | null {
  if (!reached(station.state) || index === 0) return null
  const gate = station.spot.at === 'gate'
  const agent = station.spot.at === 'agent' && station.agent !== null && station.agent.id !== 'planner'
  if (!gate && !agent) return null
  const kind: WireKind = station.state === 'err' ? 'cut' : gate ? 'gate' : 'ai'
  return { id: `plan:${index}`, kind, from: 'planner', to: index }
}

/** The stage for a run line, or null when the line is empty or too long and the plain step line draws it. */
export function stageOf(stations: readonly Station[]): StageModel | null {
  if (stations.length === 0 || stations.length > MAX_STAGE_STEPS) return null
  const nodes = stations.map(
    (station): StageNode => ({
      key: station.key,
      label: station.label,
      state: station.state,
      picture: station.spot.at === 'agent' && station.agent !== null ? 'face' : 'icon',
      agent: station.agent,
      face: station.face,
      icon: station.icon,
      gate: station.spot.at === 'gate',
      under: station.under,
    }),
  )
  const wires = stations.flatMap((station, index): Wire[] => {
    if (index === 0) return []
    const track: Wire = { id: `track:${index}`, kind: reached(station.state) ? 'track' : 'todo', from: index - 1, to: index }
    const plan = wireOf(station, index)
    return plan ? [track, plan] : [track]
  })
  return { planner: plannerFaceOf(stations), nodes, wires }
}

export interface Handoff {
  readonly id: string
  /** Seconds after the stage opens. Nothing waits once the stage is open. */
  readonly delay: number
}

/** The stage plays once when it opens, in under five seconds. */
const OPENING_STEP = 0.8
const OPENING_START = 0.2

/**
 * The hand-offs that glow. When the stage opens, every wire the run reached, in order. After that, only the wires into a step that
 * has just been reached: a stop and a decline do not glow, since nothing was handed on, and a step already reached does not glow again.
 */
export function handoffsOf(stage: StageModel, before: Readonly<Record<string, StepState>> | null): Handoff[] {
  const live = stage.wires.filter((wire) => {
    const node = stage.nodes[wire.to]
    if (!node || wire.kind === 'todo' || wire.kind === 'cut' || node.state === 'no' || node.state === 'err') return false
    const was = before?.[node.key]
    return before === null || was === undefined || !reached(was)
  })
  return live.map((wire, index) => ({ id: wire.id, delay: before === null ? Math.round((OPENING_START + index * OPENING_STEP) * 10) / 10 : 0 }))
}

const HUB = 148
const RISE = 44
const NODE_MAX = 84
const NODE_MIN = 52
const COLUMN_PAD = 20

export interface Geometry {
  readonly columns: readonly number[]
  readonly planner: { readonly x: number; readonly y: number }
  readonly node: number
  readonly centreY: number
  readonly hubHeight: number
  readonly rise: number
  readonly height: number
  /** The track between step `to - 1` and step `to`, edge to edge on the circles' centre line. */
  readonly track: (to: number) => string
  /** The Planner's wire down to the top of step `to`. */
  readonly plan: (to: number) => string
}

/** Where the parts sit for `count` steps in a stage `width` px wide. The same numbers place the wires and the steps. */
export function geometryOf(count: number, width: number): Geometry {
  const column = width / Math.max(count, 1)
  const columns = Array.from({ length: count }, (_, index) => (index + 0.5) * column)
  const node = Math.max(NODE_MIN, Math.min(NODE_MAX, Math.floor(column - COLUMN_PAD)))
  const centreY = HUB + RISE + node / 2
  const planner = { x: width / 2, y: HUB }
  const top = centreY - node / 2
  const r = (value: number) => Math.round(value * 10) / 10
  return {
    columns,
    planner,
    node,
    centreY,
    hubHeight: HUB,
    rise: RISE,
    height: centreY + node / 2,
    track: (to) => `M${r((columns[to - 1] ?? 0) + node / 2)} ${centreY}H${r((columns[to] ?? 0) - node / 2)}`,
    plan: (to) => {
      const x = columns[to] ?? 0
      const mid = HUB + RISE / 2
      return `M${r(planner.x)} ${HUB}C${r(planner.x)} ${mid} ${r(x)} ${mid} ${r(x)} ${top}`
    },
  }
}
