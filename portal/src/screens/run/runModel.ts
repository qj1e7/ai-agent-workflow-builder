import type { ApprovalStepStatus, BlockKind, FailureReason, FailureStage, RunOutcome, Trigger, Verdict } from '../../api/types'
import { runId as asRunId, type RunTime } from '../../stream/brand'
import { parseEvent, type EventOf, type RunEvent } from '../../stream/parse'
import { GATE_STEP, stepWords, writeLabel } from './words'

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
  | { readonly state: 'skipped' }
  | { readonly state: 'expired' }
  | { readonly state: 'lost' }
  | { readonly state: 'succeeded'; readonly outcome: RunOutcome }
  | { readonly state: 'rejected'; readonly by: string; readonly step: number }
  | {
      readonly state: 'failed'
      readonly stage: FailureStage
      readonly reason: FailureReason
      readonly retryable: boolean
      readonly message: string
    }

/** An agent is placed by the order it joined in. */
export type Spot =
  | { readonly at: 'started' }
  | { readonly at: 'planner' }
  | { readonly at: 'agent'; readonly index: number }
  | { readonly at: 'gate' }
  | { readonly at: 'write' }
  | { readonly at: 'done' }

/** A declined request: who said yes to the steps before, who declined, and why when they said (spec 10.5). */
export interface Declined {
  readonly by: string
  readonly approvedBy: readonly string[]
  readonly reason: string | null
}

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
  /** Where people open it, as the platform gave it. Older events have none. */
  readonly url?: string | null
}

/** One entry in the run's log, placed and timed by the event that made it. */
export type ChatItem = { readonly seq: number; readonly at: RunTime } & (
  | { readonly kind: 'started'; readonly by: string; readonly trigger: Trigger }
  | { readonly kind: 'joined'; readonly agents: readonly AgentRef[] }
  | { readonly kind: 'said'; readonly speaker: AgentRef; readonly text: string; readonly bad: boolean }
  | { readonly kind: 'asked'; readonly channel: string | null; readonly posted: boolean | null }
  | { readonly kind: 'decided'; readonly by: string; readonly verdict: Verdict; readonly step: string | null }
  | {
      readonly kind: 'written'
      readonly connector: string
      readonly operation: string
      readonly refs: readonly string[]
      readonly urls?: Readonly<Record<string, string>>
    }
  | { readonly kind: 'denied' }
  | { readonly kind: 'retried'; readonly by: string | null }
  | { readonly kind: 'finished'; readonly outcome: RunOutcome; readonly count: number; readonly operation: string | null }
  | { readonly kind: 'declined'; readonly record: Declined }
  | { readonly kind: 'stopped'; readonly stage: FailureStage }
  | { readonly kind: 'reported'; readonly by: string; readonly requestId: string }
  /** What a Tell block did, in the platform's own words: sent, not confirmed, what a test run would have sent, or nothing to report. */
  | { readonly kind: 'told'; readonly line: string; readonly bad: boolean }
)

/** A spot the run reached, and when. */
export interface Reached {
  readonly spot: Spot
  readonly at: RunTime
}

export interface RunModel {
  /** The last event folded in. Events are taken only in order, so this is also how many there are. */
  readonly seq: number
  readonly startedBy: string | null
  readonly trigger: Trigger
  readonly useCaseId: string | null
  readonly phase: Phase
  readonly spot: Spot
  readonly spotSeq: number
  /** The spots this attempt reached, in order, from its start. The timer under the step at work counts from the first one the step covers. */
  readonly reached: readonly Reached[]
  readonly agents: readonly AgentRef[]
  readonly failedAt: Spot | null
  readonly approvalId: string | null
  readonly steps: readonly ApprovalStep[]
  readonly proposed: number
  readonly connector: string | null
  readonly written: readonly Written[]
  readonly approvedBy: readonly string[]
  /** Why the Approver declined, from the decline event, when they gave a reason. */
  readonly declineReason: string | null
  readonly retriedBy: readonly string[]
  /** What the agents said they found, from the step that closed their work. Kept after the approval stops carrying it. */
  readonly found: string
  /** The reports to support about this stop, one for each request. A retry starts the list again. */
  readonly reports: readonly { readonly requestId: string; readonly by: string }[]
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
  reached: [],
  agents: [],
  failedAt: null,
  approvalId: null,
  steps: [],
  proposed: 0,
  connector: null,
  written: [],
  approvedBy: [],
  declineReason: null,
  retriedBy: [],
  found: '',
  reports: [],
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

type When = Pick<RunEvent, 'seq' | 'at'>

function advanceTo(model: RunModel, spot: Spot, event: When): RunModel {
  if (rank(spot) <= rank(model.spot)) return model
  return { ...model, spot, spotSeq: event.seq, reached: [...model.reached, { spot, at: event.at }] }
}

function placeAgent(model: RunModel, agent: AgentRef): { model: RunModel; spot: Spot } {
  if (agent.id === PLANNER_ID) return { model, spot: { at: 'planner' } }
  const index = model.agents.findIndex((known) => known.id === agent.id)
  if (index >= 0) return { model, spot: { at: 'agent', index } }
  return { model: { ...model, agents: [...model.agents, agent] }, spot: { at: 'agent', index: model.agents.length } }
}

function touch(model: RunModel, agent: AgentRef, event: When): RunModel {
  const placed = placeAgent(model, agent)
  return working(advanceTo(placed.model, placed.spot, event))
}

function working(model: RunModel): RunModel {
  return model.phase.state === 'pending' ? { ...model, phase: { state: 'working' } } : model
}

function say(model: RunModel, item: ChatItem): RunModel {
  return { ...model, chat: [...model.chat, item] }
}

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
  const placed = placeAgent(touch(model, actorRef(event), event), agent).model
  const last = placed.chat.at(-1)
  if (last?.kind === 'joined') {
    if (last.agents.some((known) => known.id === agent.id)) return placed
    return { ...placed, chat: [...placed.chat.slice(0, -1), { ...last, agents: [...last.agents, agent] }] }
  }
  return say(placed, { kind: 'joined', seq: event.seq, at: event.at, agents: [agent] })
}

function decided(model: RunModel, event: EventOf<'approval_decided'>): RunModel {
  const { step, verdict, by } = event.data
  const steps = model.steps.map((s) =>
    s.index === step ? { ...s, status: verdict === 'approve' ? ('approved' as const) : ('declined' as const), by } : s,
  )
  const label = steps.length > 1 ? (steps.find((s) => s.index === step)?.label ?? null) : null
  let next = say({ ...model, steps }, { kind: 'decided', seq: event.seq, at: event.at, by, verdict, step: label })
  if (verdict === 'approve') {
    next = { ...next, approvedBy: next.approvedBy.includes(by) ? next.approvedBy : [...next.approvedBy, by] }
    const allApproved = steps.length === 0 || steps.every((s) => s.status === 'approved')
    if (allApproved) next = advanceTo({ ...next, phase: { state: 'acting' } }, { at: 'write' }, event)
  }
  return next
}

function wrote(model: RunModel, event: EventOf<'write_action_done'>): RunModel {
  const { connector, operation, external_reference: ref } = event.data
  const url = event.data.url ?? null
  let next: RunModel = { ...model, connector, written: [...model.written, { connector, operation, ref, url }], phase: { state: 'acting' } }
  next = advanceTo(next, { at: 'write' }, event)
  const linked = url === null ? {} : { [ref]: url }
  const last = next.chat.at(-1)
  if (last?.kind === 'written' && last.connector === connector && last.operation === operation) {
    return { ...next, chat: [...next.chat.slice(0, -1), { ...last, refs: [...last.refs, ref], urls: { ...last.urls, ...linked } }] }
  }
  return say(next, { kind: 'written', seq: event.seq, at: event.at, connector, operation, refs: [ref], urls: linked })
}

function retried(model: RunModel, event: EventOf<'run_retried'>): RunModel {
  const by = event.actor.kind === 'user' ? event.actor.id : null
  const spot: Spot = event.data.leg === 'work' ? { at: 'started' } : { at: 'write' }
  const base: RunModel = {
    ...model,
    failedAt: null,
    retriedBy: by === null || model.retriedBy.includes(by) ? model.retriedBy : [...model.retriedBy, by],
    spot,
    spotSeq: event.seq,
    reached: [{ spot, at: event.at }],
    reports: [],
  }
  const next: RunModel =
    event.data.leg === 'work'
      ? { ...base, phase: { state: 'pending' }, agents: [], approvalId: null, steps: [], proposed: 0, written: [], found: '' }
      : { ...base, phase: { state: 'acting' } }
  return say(next, { kind: 'retried', seq: event.seq, at: event.at, by })
}

/** The outcomes of the agents' step that carry their summary. A failed step carries an error. */
const FOUND_OUTCOMES: ReadonlySet<string> = new Set(['proposed', 'nothing_to_write'])

function reported(model: RunModel, event: EventOf<'support_reported'>): RunModel {
  const { request_id: requestId, reported_by: by } = event.data
  if (model.reports.some((report) => report.requestId === requestId)) return model
  return say({ ...model, reports: [...model.reports, { requestId, by }] }, { kind: 'reported', seq: event.seq, at: event.at, by, requestId })
}

function apply(model: RunModel, event: RunEvent): RunModel {
  switch (event.kind) {
    case 'run_created': {
      const { started_by: by, trigger, use_case_id: useCaseId } = event.data
      return say(
        { ...model, startedBy: by, trigger: trigger ?? 'person', useCaseId, phase: { state: 'pending' }, reached: [{ spot: { at: 'started' }, at: event.at }] },
        { kind: 'started', seq: event.seq, at: event.at, by, trigger: trigger ?? 'person' },
      )
    }
    case 'agent_joined':
      return joined(model, event)
    case 'agent_message':
      return say(touch(model, event.data.speaker, event), {
        kind: 'said',
        seq: event.seq, at: event.at,
        speaker: event.data.speaker,
        text: event.data.text,
        bad: false,
      })
    case 'agent_step_started':
    case 'agent_step_finished':
      return touch(model, actorRef(event), event)
    case 'agent_failed': {
      const touched = touch(model, actorRef(event), event)
      const failedAt = placeAgent(touched, actorRef(event)).spot
      return say({ ...touched, failedAt }, { kind: 'said', seq: event.seq, at: event.at, speaker: actorRef(event), text: event.data.message, bad: true })
    }
    case 'write_action_proposed': {
      const phase = model.phase.state === 'pending' || model.phase.state === 'working' ? { state: 'proposed' as const } : model.phase
      return { ...model, phase, proposed: event.data.actions.length, connector: event.data.actions[0]?.connector ?? model.connector }
    }
    case 'approval_requested': {
      const steps = event.data.steps.map((s) => ({ index: s.index, label: s.label, status: s.status, by: s.decided_by ?? null }))
      const next = advanceTo({ ...model, approvalId: event.data.approval_id, steps, phase: { state: 'awaiting_approval' } }, { at: 'gate' }, event)
      return say(next, { kind: 'asked', seq: event.seq, at: event.at, channel: null, posted: null })
    }
    case 'approval_announced':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, at: item?.at ?? event.at, channel: event.data.channel, posted: true }))
    case 'approval_announce_failed':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, at: item?.at ?? event.at, channel: event.data.channel, posted: false }))
    case 'approval_decided':
      return decided(model, event)
    case 'write_action_denied':
      return say(model, { kind: 'denied', seq: event.seq, at: event.at })
    case 'write_action_done':
      return wrote(model, event)
    case 'run_succeeded': {
      const next = advanceTo({ ...model, phase: { state: 'succeeded', outcome: event.data.outcome } }, { at: 'done' }, event)
      return say(next, {
        kind: 'finished',
        seq: event.seq, at: event.at,
        outcome: event.data.outcome,
        count: model.written.length,
        operation: model.written[0]?.operation ?? null,
      })
    }
    case 'run_rejected': {
      const { by, step } = event.data
      const record: Declined = { by, approvedBy: model.approvedBy, reason: event.data.reason ?? null }
      const next = advanceTo({ ...model, phase: { state: 'rejected', by, step }, declineReason: record.reason }, { at: 'done' }, event)
      return say(next, { kind: 'declined', seq: event.seq, at: event.at, record })
    }
    case 'run_failed': {
      const { stage, reason, retryable, message } = event.data
      return say(
        { ...model, failedAt: failedSpot(model, stage), phase: { state: 'failed', stage, reason, retryable, message } },
        { kind: 'stopped', seq: event.seq, at: event.at, stage },
      )
    }
    case 'run_retried':
      return retried(model, event)
    case 'step_finished':
      return event.data.step === 'run_agents' && FOUND_OUTCOMES.has(event.data.outcome) && event.data.detail ? { ...model, found: event.data.detail } : model
    case 'support_reported':
      return reported(model, event)
    case 'told':
      return say(model, { kind: 'told', seq: event.seq, at: event.at, line: event.data.line, bad: event.data.status === 'not_confirmed' })
    case 'run_skipped':
      return advanceTo({ ...model, phase: { state: 'skipped' } }, { at: 'done' }, event)
    case 'run_expired':
      return advanceTo({ ...model, phase: { state: 'expired' } }, { at: 'done' }, event)
    case 'run_lost':
      return advanceTo({ ...model, phase: { state: 'lost' } }, { at: 'done' }, event)
    case 'leg_dispatched':
    case 'execution_linked':
    case 'execution_resumed':
    case 'step_started':
    case 'step_retried':
    case 'approval_outcome_not_posted':
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
  readonly key: string
  readonly name: string
  readonly kind: BlockKind
}

export type StationState = 'todo' | 'now' | 'wait' | 'done' | 'err' | 'no' | 'skip'
export type FaceState = 'idle' | 'thinking' | 'working' | 'waiting' | 'success' | 'error' | 'stopped'
/** The picture in a step's dot: the clock or the person that started the run, an agent reading, the gate, the write. */
export type StepIcon = 'schedule' | 'person' | 'read' | 'gate' | 'write'

/** What a step says under its name. */
export type Under =
  | { readonly kind: 'timer'; readonly since: RunTime }
  | { readonly kind: 'tickets'; readonly written: readonly Written[] }
  | { readonly kind: 'note'; readonly text: string }

export interface Station {
  readonly key: string
  readonly spot: Spot
  readonly label: string
  readonly icon: StepIcon
  /** The agent above an agent's step, once it joined. */
  readonly agent: AgentRef | null
  readonly state: StationState
  readonly face: FaceState
  readonly under: Under | null
}

type Skeleton = Pick<Station, 'key' | 'spot' | 'label' | 'icon' | 'agent'>

function skeleton(model: RunModel, plan: readonly PlanBlock[] | null, trigger: string): Skeleton[] {
  const agentBlocks = plan?.filter((block) => block.kind === 'agent') ?? []
  const writeBlock = plan?.find((block) => block.kind === 'write_action')
  const hasGate = plan === null || plan.some((block) => block.kind === 'approval')
  const hasWrite = plan === null || writeBlock !== undefined
  const count = Math.max(agentBlocks.length, model.agents.length, 1)
  const agents = Array.from({ length: count }, (_, index): Skeleton => {
    const agent = model.agents[index] ?? null
    const block = agentBlocks[index]
    return { key: `agent:${index}`, spot: { at: 'agent', index }, label: block ? stepWords(block) : (agent?.display ?? 'Agent'), icon: 'read', agent }
  })
  return [
    { key: 'trigger', spot: { at: 'started' }, label: trigger, icon: model.trigger === 'schedule' ? 'schedule' : 'person', agent: null },
    ...agents,
    ...(hasGate ? [{ key: 'gate', spot: { at: 'gate' }, label: GATE_STEP, icon: 'gate', agent: null } as const] : []),
    ...(hasWrite ? [{ key: 'write', spot: { at: 'write' }, label: writeBlock ? stepWords(writeBlock) : writeLabel(model.connector), icon: 'write', agent: null } as const] : []),
  ]
}

function stationAtOrAfter(stations: readonly Skeleton[], spot: Spot | null): number {
  if (spot === null) return -1
  const exact = stations.findIndex((station) => sameSpot(station.spot, spot))
  if (exact >= 0) return exact
  return stations.findIndex((station) => rank(station.spot) > rank(spot))
}

/** The step a spot is drawn at. The start is the first step, done once the run exists, so the Planner's pick runs under the step after it. */
function stationOf(stations: readonly Skeleton[], spot: Spot | null): number {
  return stationAtOrAfter(stations, spot?.at === 'started' ? { at: 'planner' } : spot)
}

function stateOf(model: RunModel, station: Skeleton, index: number, current: number, failed: number): StationState {
  const { phase } = model
  const at = station.spot.at
  const unfilled = at === 'agent' && station.agent === null
  if (at === 'started') return 'done'
  switch (phase.state) {
    case 'failed':
      if (index === failed) return 'err'
      return index < failed ? (unfilled ? 'skip' : 'done') : 'todo'
    case 'succeeded':
      if (phase.outcome === 'nothing_to_write' && (at === 'gate' || at === 'write')) return 'skip'
      return unfilled ? 'skip' : 'done'
    case 'rejected':
      if (at === 'gate') return 'no'
      if (at === 'write') return 'skip'
      return unfilled ? 'skip' : 'done'
    case 'skipped':
      return 'skip'
    case 'expired':
    case 'lost':
      if (at === 'gate') return phase.state === 'lost' ? 'done' : 'skip'
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

const FACE: Readonly<Record<StationState, FaceState>> = { todo: 'idle', now: 'working', wait: 'waiting', done: 'success', err: 'error', no: 'idle', skip: 'stopped' }
const PLANNER: AgentRef = { id: PLANNER_ID, display: 'Planner' }

/** Before any agent joins, the Planner is picking them under the first step, so its face is the one at work there, or stopped. */
function faceAgent(model: RunModel, station: Skeleton, state: StationState): AgentRef | null {
  if (station.agent || station.key !== 'agent:0' || model.agents.length > 0) return station.agent
  return state === 'now' || state === 'err' ? PLANNER : null
}

/** When the step at work began: the first spot this attempt reached that the step covers. */
function sinceOf(model: RunModel, stations: readonly Skeleton[], index: number): RunTime | null {
  return model.reached.find((reached) => stationOf(stations, reached.spot) === index)?.at ?? null
}

function underOf(model: RunModel, stations: readonly Skeleton[], index: number, state: StationState): Under | null {
  const at = stations[index]?.spot.at
  if (state === 'now') {
    const since = sinceOf(model, stations, index)
    return since === null ? null : { kind: 'timer', since }
  }
  const written = model.written.filter((write) => write.ref !== '')
  if (at === 'write' && state === 'done' && written.length > 0) return { kind: 'tickets', written }
  if (at === 'write' && state === 'skip' && model.phase.state === 'rejected') return { kind: 'note', text: 'Nothing written' }
  return null
}

/**
 * The run line: the workflow's blocks and nothing else. What started the run, one step per agent, the gate and the write.
 * The plan, when known, names the steps and fixes how many there are, so the line does not grow as agents join.
 */
export function stationsOf(model: RunModel, plan: readonly PlanBlock[] | null, trigger: string): Station[] {
  const stations = skeleton(model, plan, trigger)
  const current = stationOf(stations, model.spot)
  const failed = model.phase.state === 'failed' ? stationOf(stations, model.failedAt) : -1
  return stations.map((station, index) => {
    const state = stateOf(model, station, index, current, failed)
    const agent = faceAgent(model, station, state)
    const face = agent === null ? 'idle' : agent.id === PLANNER_ID && state === 'now' ? 'thinking' : FACE[state]
    return { ...station, agent, state, face, under: underOf(model, stations, index, state) }
  })
}

/** A declined run's record: who said yes first, who declined, and why. Null for a run that wasn't declined. */
export function declinedOf(model: RunModel): Declined | null {
  const { phase } = model
  return phase.state === 'rejected' ? { by: phase.by, approvedBy: model.approvedBy, reason: model.declineReason } : null
}

export function isFinished(phase: Phase): boolean {
  return ['succeeded', 'rejected', 'failed', 'skipped', 'expired', 'lost'].includes(phase.state)
}
