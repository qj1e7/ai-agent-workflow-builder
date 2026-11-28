import type { StepIcon, StepState } from '../../ui/StepLine'
import type { AgentRef, FaceState, Phase, Station, Under } from './runModel'

/** The stage is drawn for one line of up to this many steps. A longer line falls back to the plain step line (ADR 0052). */
export const MAX_STAGE_STEPS = 6

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
 * A wire: the track between two steps, or the Planner's hand-off to an agent (violet) or to the gate (amber). A track to a step not
 * reached is dashed.
 */
export type WireKind = 'track' | 'ai' | 'gate' | 'todo'

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
  readonly nodes: readonly StageNode[]
  readonly wires: readonly Wire[]
}

/**
 * The Planner's face follows the run's own state, the one its pill says: at work while the run goes, up with a clock while the gate
 * waits, smiling only when the run succeeded, and frowning when it stopped. A run that was declined, expired, lost or skipped is neither.
 */
export function plannerFaceOf(phase: Phase['state']): FaceState {
  switch (phase) {
    case 'pending':
    case 'working':
    case 'proposed':
    case 'acting':
      return 'thinking'
    case 'awaiting_approval':
      return 'waiting'
    case 'succeeded':
      return 'success'
    case 'failed':
      return 'error'
    default:
      return 'idle'
  }
}

function wireOf(station: Station, index: number): Wire | null {
  if (!reached(station.state) || index === 0) return null
  const gate = station.spot.at === 'gate'
  const agent = station.spot.at === 'agent' && station.agent !== null && station.agent.id !== 'planner'
  if (!gate && !agent) return null
  const kind: WireKind = gate ? 'gate' : 'ai'
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
  return { nodes, wires }
}

export interface Handoff {
  readonly id: string
  /** Seconds after the stage opens. Nothing waits once the stage is open. */
  readonly delay: number
}

/** The stage plays once when it opens, in under five seconds: each hand-off runs for this long, and the opening has this long in all. */
const TRAVEL = 0.8
const OPENING = 5
const OPENING_START = 0.2
const OPENING_STEP = 0.8

/**
 * The hand-offs that glow. When the stage opens, every wire the run reached, in order, into a stop or a declined gate too, as the sketch
 * plays it, and as the run line first showed the work flowing into a stop. The pace slows down to fit six steps in the opening. After that,
 * only the wires into a step whose state just changed, a retry's flow into the step again included. A stop and a decline that just
 * happened do not glow, since nothing was handed on.
 */
export function handoffsOf(stage: StageModel, before: Readonly<Record<string, StepState>> | null): Handoff[] {
  const live = stage.wires.filter((wire) => {
    const node = stage.nodes[wire.to]
    if (!node || wire.kind === 'todo') return false
    if (before === null) return true
    return node.state !== 'err' && node.state !== 'no' && before[node.key] !== node.state
  })
  const step = live.length > 1 ? Math.min(OPENING_STEP, (OPENING - OPENING_START - TRAVEL) / (live.length - 1)) : OPENING_STEP
  const delay = (index: number) => Math.floor((OPENING_START + index * step) * 100) / 100
  return live.map((wire, index) => ({ id: wire.id, delay: before === null ? delay(index) : 0 }))
}

/** Where the stopped step sits across the stage, as a share of its width: the middle of its column. Null when no step stopped or the stage is not drawn. */
export function stoppedAt(stations: readonly Station[]): number | null {
  if (stageOf(stations) === null) return null
  const index = stations.findIndex((station) => station.state === 'err')
  return index < 0 ? null : (index + 0.5) / stations.length
}

/** Where the troubleshooter's notch points: the stopped step on the main view, and nothing in the n8n view, where no stage is drawn. */
export function stopPointer(view: 'main' | 'n8n', stations: readonly Station[]): number | null {
  return view === 'n8n' ? null : stoppedAt(stations)
}

/** When the circle at the end of a wire turns blue on opening: as its own hand-off arrives. */
export const ARRIVES = TRAVEL

const HUB = 112
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
