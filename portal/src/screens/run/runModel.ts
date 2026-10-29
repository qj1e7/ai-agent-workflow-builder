import type { ApprovalStepStatus, BlockKind, FailureReason, FailureStage, RunOutcome, Trigger, Verdict } from '../../api/types'
import { runId as asRunId } from '../../stream/brand'
import { parseEvent, type EventOf, type RunEvent } from '../../stream/parse'

export const PLANNER_ID = 'planner'

export interface AgentRef {
  readonly id: string
  readonly display: string
}

export type Phase =
  | { readonly state: 'pending' }
  | { readonly state: 'working' }
  | { readonly state: 'proposed' }
  | { readonly state: 'awaiting_approval' }
  | { readonly state: 'acting' }
  | { readonly state: 'succeeded'; readonly outcome: RunOutcome }
  | { readonly state: 'rejected'; readonly by: string; readonly step: number }
  | {
      readonly state: 'failed'
      readonly stage: FailureStage
      readonly reason: FailureReason
      readonly retryable: boolean
      readonly message: string
    }

/** Where the run is on its line. An agent is placed by the order it joined in. */
export type Spot =
  | { readonly at: 'started' }
  | { readonly at: 'planner' }
  | { readonly at: 'agent'; readonly index: number }
  | { readonly at: 'gate' }
  | { readonly at: 'write' }
  | { readonly at: 'done' }

export interface ApprovalStep {
  readonly index: number
  readonly label: string
  readonly status: ApprovalStepStatus
  readonly by: string | null
}

export interface Written {
  readonly connector: string
  readonly operation: string
  readonly ref: string
}

export type ChatItem =
  | { readonly kind: 'started'; readonly seq: number; readonly by: string; readonly trigger: Trigger }
  | { readonly kind: 'joined'; readonly seq: number; readonly agents: readonly AgentRef[] }
  | { readonly kind: 'said'; readonly seq: number; readonly speaker: AgentRef; readonly text: string; readonly bad: boolean }
  | { readonly kind: 'asked'; readonly seq: number; readonly channel: string | null; readonly posted: boolean | null }
  | { readonly kind: 'decided'; readonly seq: number; readonly by: string; readonly verdict: Verdict; readonly step: string | null }
  | { readonly kind: 'written'; readonly seq: number; readonly connector: string; readonly operation: string; readonly refs: readonly string[] }
  | { readonly kind: 'denied'; readonly seq: number }
  | { readonly kind: 'retried'; readonly seq: number; readonly by: string | null }
  | { readonly kind: 'finished'; readonly seq: number; readonly outcome: RunOutcome; readonly count: number; readonly operation: string | null }
  | { readonly kind: 'declined'; readonly seq: number }
  | { readonly kind: 'stopped'; readonly seq: number; readonly stage: FailureStage }

export interface RunModel {
  /** The last event folded in. Events are taken only in order, so this is also how many there are. */
  readonly seq: number
  readonly startedBy: string | null
  readonly trigger: Trigger
  readonly useCaseId: string | null
  readonly phase: Phase
  readonly spot: Spot
  /** The event that last moved the spot, so a page can tell a step reached just now from one it loaded. */
  readonly spotSeq: number
  readonly agents: readonly AgentRef[]
  readonly failedAt: Spot | null
  readonly approvalId: string | null
  readonly steps: readonly ApprovalStep[]
  readonly proposed: number
  readonly connector: string | null
  readonly written: readonly Written[]
  readonly approvedBy: readonly string[]
  readonly retriedBy: readonly string[]
  /** Display names of the people the events name, by id. */
  readonly people: Readonly<Record<string, string>>
  readonly chat: readonly ChatItem[]
}

export const emptyModel: RunModel = {
  seq: 0,
  startedBy: null,
  trigger: 'person',
  useCaseId: null,
  phase: { state: 'pending' },
  spot: { at: 'started' },
  spotSeq: 0,
  agents: [],
  failedAt: null,
  approvalId: null,
  steps: [],
  proposed: 0,
  connector: null,
  written: [],
  approvedBy: [],
  retriedBy: [],
  people: {},
  chat: [],
}

const RANK: Readonly<Record<Spot['at'], number>> = { started: 0, planner: 1, agent: 2, gate: 3, write: 4, done: 5 }

function rank(spot: Spot): number {
  return RANK[spot.at] + (spot.at === 'agent' ? spot.index / 1000 : 0)
}

export function sameSpot(a: Spot | null, b: Spot | null): boolean {
  if (a === null || b === null) return a === b
  return a.at === b.at && (a.at !== 'agent' || (b.at === 'agent' && a.index === b.index))
}

/** The spot only moves forward. A Planner that speaks again after its agents does not pull the line back. */
function moveTo(model: RunModel, spot: Spot, seq: number): RunModel {
  return rank(spot) > rank(model.spot) ? { ...model, spot, spotSeq: seq } : model
}

function placeAgent(model: RunModel, agent: AgentRef): { model: RunModel; spot: Spot } {
  if (agent.id === PLANNER_ID) return { model, spot: { at: 'planner' } }
  const index = model.agents.findIndex((known) => known.id === agent.id)
  if (index >= 0) return { model, spot: { at: 'agent', index } }
  return { model: { ...model, agents: [...model.agents, agent] }, spot: { at: 'agent', index: model.agents.length } }
}

/** An agent did something, so the line reaches its step. */
function touch(model: RunModel, agent: AgentRef, seq: number): RunModel {
  const placed = placeAgent(model, agent)
  return working(moveTo(placed.model, placed.spot, seq))
}

function working(model: RunModel): RunModel {
  return model.phase.state === 'pending' ? { ...model, phase: { state: 'working' } } : model
}

function say(model: RunModel, item: ChatItem): RunModel {
  return { ...model, chat: [...model.chat, item] }
}

/** Replaces the newest chat item of a kind, or adds one when there is none. */
function amendLast<K extends ChatItem['kind']>(
  model: RunModel,
  kind: K,
  change: (item: Extract<ChatItem, { kind: K }> | null) => Extract<ChatItem, { kind: K }>,
): RunModel {
  for (let at = model.chat.length - 1; at >= 0; at -= 1) {
    const item = model.chat[at]
    if (item?.kind === kind) {
      const chat = [...model.chat]
      chat[at] = change(item as Extract<ChatItem, { kind: K }>)
      return { ...model, chat }
    }
  }
  return say(model, change(null))
}

function actorRef(event: RunEvent): AgentRef {
  return { id: event.actor.id, display: event.actor.display }
}

function learnPeople(model: RunModel, event: RunEvent): RunModel {
  const { kind, id, display } = event.actor
  if (kind !== 'user' || model.people[id] === display) return model
  return { ...model, people: { ...model.people, [id]: display } }
}

function failedSpot(model: RunModel, stage: FailureStage): Spot {
  if (model.failedAt) return model.failedAt
  switch (stage) {
    case 'pending':
      return { at: 'planner' }
    case 'working':
      return model.spot.at === 'started' ? { at: 'planner' } : model.spot
    case 'proposed':
      return { at: 'gate' }
    case 'acting':
      return { at: 'write' }
  }
}

function joined(model: RunModel, event: EventOf<'agent_joined'>): RunModel {
  const agent = event.data.agent
  const placed = placeAgent(touch(model, actorRef(event), event.seq), agent).model
  const last = placed.chat.at(-1)
  if (last?.kind === 'joined') {
    if (last.agents.some((known) => known.id === agent.id)) return placed
    return { ...placed, chat: [...placed.chat.slice(0, -1), { ...last, agents: [...last.agents, agent] }] }
  }
  return say(placed, { kind: 'joined', seq: event.seq, agents: [agent] })
}

function decided(model: RunModel, event: EventOf<'approval_decided'>): RunModel {
  const { step, verdict, by } = event.data
  const steps = model.steps.map((s) =>
    s.index === step ? { ...s, status: verdict === 'approve' ? ('approved' as const) : ('declined' as const), by } : s,
  )
  const label = steps.length > 1 ? (steps.find((s) => s.index === step)?.label ?? null) : null
  let next = say({ ...model, steps }, { kind: 'decided', seq: event.seq, by, verdict, step: label })
  if (verdict === 'approve') {
    next = { ...next, approvedBy: next.approvedBy.includes(by) ? next.approvedBy : [...next.approvedBy, by] }
    const allApproved = steps.length === 0 || steps.every((s) => s.status === 'approved')
    if (allApproved) next = moveTo({ ...next, phase: { state: 'acting' } }, { at: 'write' }, event.seq)
  }
  return next
}

function wrote(model: RunModel, event: EventOf<'write_action_done'>): RunModel {
  const { connector, operation, external_reference: ref } = event.data
  let next: RunModel = { ...model, connector, written: [...model.written, { connector, operation, ref }], phase: { state: 'acting' } }
  next = moveTo(next, { at: 'write' }, event.seq)
  const last = next.chat.at(-1)
  if (last?.kind === 'written' && last.connector === connector && last.operation === operation) {
    return { ...next, chat: [...next.chat.slice(0, -1), { ...last, refs: [...last.refs, ref] }] }
  }
  return say(next, { kind: 'written', seq: event.seq, connector, operation, refs: [ref] })
}

function retried(model: RunModel, event: EventOf<'run_retried'>): RunModel {
  const by = event.actor.kind === 'user' ? event.actor.id : null
  const base: RunModel = {
    ...model,
    failedAt: null,
    retriedBy: by === null || model.retriedBy.includes(by) ? model.retriedBy : [...model.retriedBy, by],
    spotSeq: event.seq,
  }
  const next: RunModel =
    event.data.leg === 'work'
      ? { ...base, phase: { state: 'pending' }, spot: { at: 'started' }, agents: [], approvalId: null, steps: [], proposed: 0, written: [] }
      : { ...base, phase: { state: 'acting' }, spot: { at: 'write' } }
  return say(next, { kind: 'retried', seq: event.seq, by })
}

function apply(model: RunModel, event: RunEvent): RunModel {
  switch (event.kind) {
    case 'run_created': {
      const { started_by: by, trigger, use_case_id: useCaseId } = event.data
      return say(
        { ...model, startedBy: by, trigger: trigger ?? 'person', useCaseId, phase: { state: 'pending' } },
        { kind: 'started', seq: event.seq, by, trigger: trigger ?? 'person' },
      )
    }
    case 'agent_joined':
      return joined(model, event)
    case 'agent_message':
      return say(touch(model, event.data.speaker, event.seq), {
        kind: 'said',
        seq: event.seq,
        speaker: event.data.speaker,
        text: event.data.text,
        bad: false,
      })
    case 'agent_step_started':
    case 'agent_step_finished':
      return touch(model, actorRef(event), event.seq)
    case 'agent_failed': {
      const touched = touch(model, actorRef(event), event.seq)
      const failedAt = placeAgent(touched, actorRef(event)).spot
      return say({ ...touched, failedAt }, { kind: 'said', seq: event.seq, speaker: actorRef(event), text: event.data.message, bad: true })
    }
    case 'write_action_proposed': {
      const phase = model.phase.state === 'pending' || model.phase.state === 'working' ? { state: 'proposed' as const } : model.phase
      return { ...model, phase, proposed: event.data.actions.length, connector: event.data.actions[0]?.connector ?? model.connector }
    }
    case 'approval_requested': {
      const steps = event.data.steps.map((s) => ({ index: s.index, label: s.label, status: s.status, by: s.decided_by ?? null }))
      const next = moveTo({ ...model, approvalId: event.data.approval_id, steps, phase: { state: 'awaiting_approval' } }, { at: 'gate' }, event.seq)
      return say(next, { kind: 'asked', seq: event.seq, channel: null, posted: null })
    }
    case 'approval_announced':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, channel: event.data.channel, posted: true }))
    case 'approval_announce_failed':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, channel: event.data.channel, posted: false }))
    case 'approval_decided':
      return decided(model, event)
    case 'write_action_denied':
      return say(model, { kind: 'denied', seq: event.seq })
    case 'write_action_done':
      return wrote(model, event)
    case 'run_succeeded': {
      const next = moveTo({ ...model, phase: { state: 'succeeded', outcome: event.data.outcome } }, { at: 'done' }, event.seq)
      return say(next, {
        kind: 'finished',
        seq: event.seq,
        outcome: event.data.outcome,
        count: model.written.length,
        operation: model.written[0]?.operation ?? null,
      })
    }
    case 'run_rejected': {
      const next = moveTo({ ...model, phase: { state: 'rejected', by: event.data.by, step: event.data.step } }, { at: 'done' }, event.seq)
      return say(next, { kind: 'declined', seq: event.seq })
    }
    case 'run_failed': {
      const { stage, reason, retryable, message } = event.data
      return say(
        { ...model, failedAt: failedSpot(model, stage), phase: { state: 'failed', stage, reason, retryable, message } },
        { kind: 'stopped', seq: event.seq, stage },
      )
    }
    case 'run_retried':
      return retried(model, event)
    case 'leg_dispatched':
    case 'step_started':
    case 'step_finished':
    case 'step_retried':
    case 'opaque':
      return model
  }
}

/**
 * Folds one event in. Pure and total: an event that is not the next one is ignored, so a repeat or a gap changes
 * nothing, and a kind the page does not draw moves only the cursor.
 */
export function fold(model: RunModel, event: RunEvent): RunModel {
  if (event.seq !== model.seq + 1) return model
  return { ...apply(learnPeople(model, event), event), seq: event.seq }
}

export function foldAll(model: RunModel, events: readonly RunEvent[]): RunModel {
  return events.reduce(fold, model)
}

/** Folds events as the platform sends them. An event whose envelope does not parse is skipped, as the feed skips it. */
export function foldWire(model: RunModel, raw: readonly unknown[], runId: string): RunModel {
  const id = asRunId(runId)
  return raw.reduce<RunModel>((folded, item) => {
    const parsed = parseEvent(item, id)
    return parsed.ok ? fold(folded, parsed.event) : folded
  }, model)
}

export interface PlanBlock {
  readonly name: string
  readonly kind: BlockKind
}

export type StationState = 'done' | 'now' | 'todo' | 'wait' | 'skip' | 'fail' | 'declined'
export type FaceState = 'idle' | 'thinking' | 'working' | 'waiting' | 'success' | 'error' | 'stopped'

export type StationWho =
  | { readonly kind: 'person'; readonly id: string }
  | { readonly kind: 'agent'; readonly agent: AgentRef | null }
  | { readonly kind: 'platform' }
  | { readonly kind: 'none' }

export interface Station {
  readonly key: string
  readonly spot: Spot
  readonly label: string
  /** The agent's name under a step the plan named, or nothing. The page puts state words here instead. */
  readonly sub: string | null
  readonly who: StationWho
  readonly state: StationState
  readonly face: FaceState
}

interface Skeleton {
  readonly key: string
  readonly spot: Spot
  readonly label: string
  readonly sub: string | null
  readonly who: StationWho
}

function skeleton(model: RunModel, plan: readonly PlanBlock[] | null, writeLabel: (connector: string | null) => string): Skeleton[] {
  const agentBlocks = plan?.filter((block) => block.kind === 'agent') ?? []
  const writeBlock = plan?.find((block) => block.kind === 'write_action')
  const hasGate = plan === null || plan.some((block) => block.kind === 'approval')
  const hasWrite = plan === null || writeBlock !== undefined
  const count = Math.max(agentBlocks.length, model.agents.length)
  const agents: Skeleton[] = Array.from({ length: count }, (_, index) => {
    const agent = model.agents[index] ?? null
    const named = agentBlocks[index]?.name
    return {
      key: `agent:${index}`,
      spot: { at: 'agent', index },
      label: named ?? agent?.display ?? 'Agent',
      sub: named && agent ? agent.display : null,
      who: { kind: 'agent', agent },
    }
  })
  return [
    { key: 'started', spot: { at: 'started' }, label: 'Started', sub: null, who: model.startedBy ? { kind: 'person', id: model.startedBy } : { kind: 'none' } },
    { key: 'planner', spot: { at: 'planner' }, label: 'Pick agents', sub: null, who: { kind: 'agent', agent: { id: PLANNER_ID, display: 'Planner' } } },
    ...agents,
    ...(hasGate ? [{ key: 'gate', spot: { at: 'gate' } as Spot, label: 'Approval gate', sub: null, who: { kind: 'none' } as StationWho }] : []),
    ...(hasWrite
      ? [{ key: 'write', spot: { at: 'write' } as Spot, label: writeBlock?.name ?? writeLabel(model.connector), sub: null, who: { kind: 'platform' } as StationWho }]
      : []),
    { key: 'done', spot: { at: 'done' }, label: 'Done', sub: null, who: { kind: 'none' } },
  ]
}

function indexOf(stations: readonly Skeleton[], spot: Spot | null): number {
  if (spot === null) return -1
  const exact = stations.findIndex((station) => sameSpot(station.spot, spot))
  if (exact >= 0) return exact
  // A plan without a gate has no gate station, so a spot there falls to the next one along.
  return stations.findIndex((station) => rank(station.spot) > rank(spot))
}

function stateOf(model: RunModel, station: Skeleton, index: number, current: number, failed: number): StationState {
  const { phase } = model
  const at = station.spot.at
  const unfilled = station.who.kind === 'agent' && station.who.agent === null
  switch (phase.state) {
    case 'failed':
      if (index === failed) return 'fail'
      return index < failed ? (unfilled ? 'skip' : 'done') : 'todo'
    case 'succeeded':
      if (phase.outcome === 'nothing_to_write' && (at === 'gate' || at === 'write')) return 'skip'
      return unfilled ? 'skip' : 'done'
    case 'rejected':
      if (at === 'gate') return 'declined'
      if (at === 'write') return 'skip'
      return unfilled ? 'skip' : 'done'
    case 'awaiting_approval':
      if (at === 'gate') return 'wait'
      break
    default:
      break
  }
  if (index < current) return unfilled ? 'skip' : 'done'
  return index === current ? 'now' : 'todo'
}

function lastAgentBefore(stations: readonly Skeleton[], states: readonly StationState[], limit: number): number {
  for (let index = Math.min(limit, stations.length) - 1; index >= 0; index -= 1) {
    const who = stations[index]?.who
    if (who?.kind === 'agent' && who.agent !== null && states[index] !== 'skip') return index
  }
  return -1
}

function faceOf(model: RunModel, station: Skeleton, state: StationState, index: number, waitingAgent: number, finalAgent: number): FaceState {
  if (station.who.kind !== 'agent') return 'idle'
  if (state === 'now') return station.spot.at === 'planner' ? 'thinking' : 'working'
  if (state === 'fail') return 'error'
  if (state === 'skip') return 'stopped'
  if (model.phase.state === 'awaiting_approval' && index === waitingAgent) return 'waiting'
  if (model.phase.state === 'succeeded' && index === finalAgent) return 'success'
  return 'idle'
}

/**
 * The run line: Started, the Planner picking agents, one step per agent, the approval gate, the write and Done.
 * The plan, when known, names the agent and write steps and fixes how many there are, so the line does not grow
 * as agents join.
 */
export function stationsOf(
  model: RunModel,
  plan: readonly PlanBlock[] | null,
  writeLabel: (connector: string | null) => string,
): Station[] {
  const stations = skeleton(model, plan, writeLabel)
  const current = indexOf(stations, model.spot)
  const failed = model.phase.state === 'failed' ? indexOf(stations, model.failedAt) : -1
  const states = stations.map((station, index) => stateOf(model, station, index, current, failed))
  const gate = stations.findIndex((station) => station.spot.at === 'gate')
  const waitingAgent = lastAgentBefore(stations, states, gate < 0 ? stations.length : gate)
  const finalAgent = lastAgentBefore(stations, states, stations.length)
  return stations.map((station, index) => {
    const state = states[index] ?? 'todo'
    return { ...station, state, face: faceOf(model, station, state, index, waitingAgent, finalAgent) }
  })
}

/** How far the line's fill reaches, from 0 at Started to 1 at Done. */
export function reachOf(stations: readonly Station[]): number {
  if (stations.length < 2) return 0
  let reached = 0
  stations.forEach((station, index) => {
    if (station.state !== 'todo') reached = index
  })
  return reached / (stations.length - 1)
}

export function isFinished(phase: Phase): boolean {
  return phase.state === 'succeeded' || phase.state === 'rejected' || phase.state === 'failed'
}
