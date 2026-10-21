import type { Actor, BlockView, FailureReason, FailureStage, RunOutcome } from '../api/types'
import type { EventOf, RunEvent } from '../stream/parse'
import { agentId, connectorKey, userId, type AgentId, type ConnectorKey, type RunTime, type Seq, type UserId } from './brand'
import { findingItems } from './finding'
import { ruleOf } from './kinds'

type DeniedReason = EventOf<'write_action_denied'>['data']['reason']

/** What the agent registry (src/ui/agents.ts) tells the engine. A port, not an import. */
export interface AgentRegistry {
  /** The Room lead. It has no block of its own: it stands with whoever it brings in or addresses. */
  readonly host: AgentRef
}

export interface AgentRef {
  readonly id: AgentId
  readonly display: string
}

export interface UserRef {
  readonly id: UserId
  readonly display: string
}

export type Phase =
  | { readonly name: 'empty' }
  | { readonly name: 'pending' }
  | { readonly name: 'working' }
  | { readonly name: 'proposed' }
  | { readonly name: 'awaiting_approval' }
  | { readonly name: 'acting' }
  | { readonly name: 'succeeded'; readonly outcome: RunOutcome }
  | { readonly name: 'rejected'; readonly by: UserRef; readonly step: number }
  | {
      readonly name: 'failed'
      readonly stage: FailureStage
      readonly reason: FailureReason
      readonly retryable: boolean
      readonly message: string
    }

/**
 * Where something happens, named by its role in the run and never by a stop index: the fold cannot see the
 * use case's blocks, which load after the tape starts. trackOf places a locus on the line the blocks give.
 */
export type Locus =
  | { readonly at: 'start' }
  /** Agent work before any specialist is known: the first agent stop. */
  | { readonly at: 'agents' }
  /** The home stop of this specialist. */
  | { readonly at: 'agent'; readonly id: AgentId }
  | { readonly at: 'draft' }
  | { readonly at: 'gate' }
  | { readonly at: 'write'; readonly connector: ConnectorKey }
  | { readonly at: 'done' }

export type AgentRole = 'host' | 'specialist'
export type AgentStatus = 'present' | 'working' | 'done' | 'stopped'

/** An agent's latest step, as its agent_step_* or agent_failed event told it. */
export interface AgentStep {
  readonly seq: Seq
  /** data.step, such as fetch_releases. agent_failed may name none. */
  readonly step: string | null
  /** The event's summary, verbatim. */
  readonly summary: string
  readonly state: 'running' | 'finished' | 'failed'
  /** agent_failed data.error_type, such as UpstreamUnavailable. */
  readonly errorType: string | null
}

export interface AgentSeat {
  readonly id: AgentId
  readonly display: string
  readonly role: AgentRole
  readonly status: AgentStatus
  /** Where it last acted. */
  readonly at: Locus
  readonly step: AgentStep | null
}

export type StepState =
  | { readonly is: 'waiting' }
  | { readonly is: 'open'; readonly since: RunTime }
  | { readonly is: 'approved'; readonly by: UserRef; readonly at: RunTime }
  | { readonly is: 'declined'; readonly by: UserRef; readonly at: RunTime }

export interface ApprovalStep {
  readonly index: number
  readonly label: string
  readonly state: StepState
}

export type OpenStep = ApprovalStep & { readonly state: Extract<StepState, { is: 'open' }> }

export type TeamsPost =
  | { readonly is: 'not_posted' }
  | { readonly is: 'posted'; readonly channel: string }
  | { readonly is: 'failed'; readonly channel: string; readonly message: string }

export interface Approval {
  readonly id: string
  readonly link: string
  /** In step order. At most one is open at a time. */
  readonly steps: readonly ApprovalStep[]
  readonly teams: TeamsPost
}

/** Every item of the step's first list, in order. */
export interface Finding {
  readonly agent: AgentId
  readonly step: string
  readonly items: readonly string[]
}

export interface TicketLine {
  readonly connector: ConnectorKey
  readonly operation: string
  /** The action line from the event, shown verbatim. */
  readonly line: string
  /** External reference once written, such as MOCK-142. */
  readonly reference: string | null
  readonly writtenAt: RunTime | null
}

export interface Ticket {
  readonly proposalId: string
  readonly digest: string
  readonly proposer: AgentId
  /** In proposal order. */
  readonly lines: readonly TicketLine[]
  readonly denied: { readonly reason: DeniedReason; readonly detail: string } | null
}

export interface Speech {
  readonly seq: Seq
  readonly speaker: AgentId
  /** agent_message data.text, verbatim. The only words the view ever puts in an agent's mouth. */
  readonly text: string
}

/** The latest captioned story event: its summary is the subline. */
export interface Latest {
  readonly seq: Seq
  readonly summary: string
  readonly actor: Actor
}

export interface RoomState {
  /** Events folded into this frame; equals the seq of the last one. */
  readonly cursor: number
  readonly startedAt: RunTime | null
  readonly attempt: number
  readonly phase: Phase
  readonly starter: UserRef | null
  /** Join order. A retry of the work leg clears them, so attempt 2 plays its arrivals again. */
  readonly agents: readonly AgentSeat[]
  /** Where the work is. */
  readonly work: Locus
  readonly approval: Approval | null
  /** Set by a step that finished with a list; cleared by a retry of the work leg. */
  readonly finding: Finding | null
  readonly ticket: Ticket | null
  /** Set by agent_message; cleared when the phase changes, a step starts or finishes, or an agent fails. */
  readonly speech: Speech | null
  readonly latest: Latest | null
}

export const EMPTY_ROOM: RoomState = {
  cursor: 0,
  startedAt: null,
  attempt: 1,
  phase: { name: 'empty' },
  starter: null,
  agents: [],
  work: { at: 'start' },
  approval: null,
  finding: null,
  ticket: null,
  speech: null,
  latest: null,
}

const START: Locus = { at: 'start' }
const DRAFT: Locus = { at: 'draft' }
const GATE: Locus = { at: 'gate' }
const DONE: Locus = { at: 'done' }

function agentLocus(id: AgentId): Locus {
  return { at: 'agent', id }
}

/** Seats an agent, or updates its seat. The host is always role 'host'; anyone else is a specialist. */
function seat(room: RoomState, who: AgentRef, registry: AgentRegistry, patch: Partial<Pick<AgentSeat, 'at' | 'status' | 'step'>>): RoomState {
  if (room.agents.some((seated) => seated.id === who.id)) {
    return { ...room, agents: room.agents.map((seated) => (seated.id === who.id ? { ...seated, ...patch } : seated)) }
  }
  const role: AgentRole = who.id === registry.host.id ? 'host' : 'specialist'
  return { ...room, agents: [...room.agents, { id: who.id, display: who.display, role, status: 'present', at: room.work, step: null, ...patch }] }
}

/** Where the host acts when it addresses no one: with the work while the work is with an agent, else at agent work. */
function hostLocus(room: RoomState): Locus {
  return room.work.at === 'agent' || room.work.at === 'agents' ? room.work : { at: 'agents' }
}

/** A specialist acts at its own stop; the host acts where the agent work is. */
function actingLocus(room: RoomState, who: AgentRef, registry: AgentRegistry): Locus {
  return who.id === registry.host.id ? hostLocus(room) : agentLocus(who.id)
}

/** The write stop of the first line not written yet. */
function writeLocus(ticket: Ticket | null): Locus | null {
  const line = ticket?.lines.find((candidate) => candidate.reference === null)
  return line ? { at: 'write', connector: line.connector } : null
}

function actorRef(actor: Actor): AgentRef {
  return { id: agentId(actor.id), display: actor.display }
}

function user(id: string, display: string): UserRef {
  return { id: userId(id), display }
}

function stepsFromWire(steps: EventOf<'approval_requested'>['data']['steps'], previous: Approval | null, at: RunTime): ApprovalStep[] {
  return steps.map((step): ApprovalStep => {
    const before = previous?.steps.find((candidate) => candidate.index === step.index)?.state
    switch (step.status) {
      case 'open':
        return { index: step.index, label: step.label, state: before?.is === 'open' ? before : { is: 'open', since: at } }
      case 'approved':
      case 'declined': {
        if (before && (before.is === 'approved' || before.is === 'declined')) return { index: step.index, label: step.label, state: before }
        const by = user(step.decided_by ?? '', step.decided_by ?? '')
        const decidedAt = (step.decided_at ? Date.parse(step.decided_at) : at) as RunTime
        return { index: step.index, label: step.label, state: { is: step.status, by, at: decidedAt } }
      }
      default:
        return { index: step.index, label: step.label, state: { is: 'waiting' } }
    }
  })
}

function decide(room: RoomState, e: EventOf<'approval_decided'>): RoomState {
  if (!room.approval) return room
  const by = user(e.data.by, e.actor.display)
  const verdict = e.data.verdict
  let steps = room.approval.steps.map((step): ApprovalStep =>
    step.index === e.data.step ? { ...step, state: { is: verdict === 'approve' ? 'approved' : 'declined', by, at: e.at } } : step,
  )
  if (verdict === 'decline') return { ...room, approval: { ...room.approval, steps } }
  const next = steps.find((step) => step.state.is === 'waiting')
  if (next) {
    steps = steps.map((step) => (step === next ? { ...step, state: { is: 'open', since: e.at } } : step))
    return { ...room, approval: { ...room.approval, steps } }
  }
  if (!steps.every((step) => step.state.is === 'approved')) return { ...room, approval: { ...room.approval, steps } }
  return { ...room, approval: { ...room.approval, steps }, phase: { name: 'acting' }, work: writeLocus(room.ticket) ?? room.work }
}

function failedWork(room: RoomState, stage: FailureStage): Locus {
  switch (stage) {
    case 'pending':
      return START
    case 'working':
      return hostLocus(room)
    case 'proposed':
      return DRAFT
    case 'acting':
      return writeLocus(room.ticket) ?? room.work
  }
}

/**
 * The fold. Pure and total: an event the state does not expect (a decision with no approval open)
 * changes only the cursor and the subline. Never throws on server data; parseEvent already checked shapes.
 */
export function applyEvent(room: RoomState, e: RunEvent, registry: AgentRegistry): RoomState {
  const rule = ruleOf(e)
  const base: RoomState = {
    ...room,
    cursor: e.seq,
    latest: rule.tier === 'story' && rule.caption ? { seq: e.seq, summary: e.summary, actor: e.actor } : room.latest,
  }
  const folded = step(base, e, registry)
  const phaseChanged = folded.phase.name !== room.phase.name
  return phaseChanged && folded.speech === room.speech ? { ...folded, speech: null } : folded
}

function step(room: RoomState, e: RunEvent, registry: AgentRegistry): RoomState {
  switch (e.kind) {
    case 'opaque':
    case 'leg_dispatched':
    case 'step_started':
    case 'step_finished':
    case 'step_retried':
      return room

    case 'run_created':
      return { ...room, startedAt: e.at, phase: { name: 'pending' }, starter: user(e.data.started_by, e.actor.display), work: START }

    case 'agent_joined': {
      const guest: AgentRef = { id: agentId(e.data.agent.id), display: e.data.agent.display }
      const work = agentLocus(guest.id)
      const brought = e.actor.kind === 'agent' ? seat({ ...room, work }, actorRef(e.actor), registry, { at: work }) : { ...room, work }
      const next = seat(brought, guest, registry, { at: work, status: 'present' })
      return { ...next, phase: next.phase.name === 'pending' || next.phase.name === 'empty' ? { name: 'working' } : next.phase }
    }

    case 'agent_step_started': {
      const agent = actorRef(e.actor)
      const at = actingLocus(room, agent, registry)
      const started = seat({ ...room, work: at, speech: null }, agent, registry, {
        at,
        status: 'working',
        step: { seq: e.seq, step: e.data.step, summary: e.summary, state: 'running', errorType: null },
      })
      return started.phase.name === 'pending' ? { ...started, phase: { name: 'working' } } : started
    }

    case 'agent_step_finished': {
      const agent = actorRef(e.actor)
      const at = actingLocus(room, agent, registry)
      const items = findingItems(e.data.result)
      const finding = items.length > 0 ? { agent: agent.id, step: e.data.step, items } : room.finding
      return seat({ ...room, work: at, finding, speech: null }, agent, registry, {
        at,
        status: 'done',
        step: { seq: e.seq, step: e.data.step, summary: e.summary, state: 'finished', errorType: null },
      })
    }

    case 'agent_failed': {
      const agent = actorRef(e.actor)
      const at = actingLocus(room, agent, registry)
      const before = room.agents.find((seated) => seated.id === agent.id)?.step?.step ?? null
      return seat({ ...room, work: at, speech: null }, agent, registry, {
        at,
        status: 'stopped',
        step: { seq: e.seq, step: e.data.step ?? before, summary: e.summary, state: 'failed', errorType: e.data.error_type },
      })
    }

    case 'agent_message': {
      const speaker: AgentRef = { id: agentId(e.data.speaker.id), display: e.data.speaker.display }
      const addressee = e.data.addressee
      const host = speaker.id === registry.host.id
      const at = !host ? agentLocus(speaker.id) : addressee.kind === 'agent' ? agentLocus(agentId(addressee.id)) : hostLocus(room)
      const work = host && addressee.kind !== 'agent' ? room.work : at
      return seat({ ...room, work, speech: { seq: e.seq, speaker: speaker.id, text: e.data.text } }, speaker, registry, { at })
    }

    case 'write_action_proposed': {
      const lines: TicketLine[] = e.data.actions.map((action) => ({
        connector: connectorKey(action.connector),
        operation: action.operation,
        line: action.line,
        reference: null,
        writtenAt: null,
      }))
      const proposer = actorRef(e.actor)
      const proposed: RoomState = {
        ...room,
        work: DRAFT,
        ticket: { proposalId: e.data.proposal_id, digest: e.data.digest, proposer: proposer.id, lines, denied: null },
        phase: { name: 'proposed' },
      }
      return e.actor.kind === 'agent' ? seat(proposed, proposer, registry, { at: DRAFT }) : proposed
    }

    case 'approval_requested': {
      const steps = stepsFromWire(e.data.steps, room.approval, e.at)
      const teams = room.approval?.id === e.data.approval_id ? room.approval.teams : { is: 'not_posted' as const }
      return { ...room, work: GATE, approval: { id: e.data.approval_id, link: e.data.link, steps, teams }, phase: { name: 'awaiting_approval' } }
    }

    case 'approval_announced':
      return room.approval ? { ...room, approval: { ...room.approval, teams: { is: 'posted', channel: e.data.channel } } } : room

    case 'approval_announce_failed':
      return room.approval
        ? { ...room, approval: { ...room.approval, teams: { is: 'failed', channel: e.data.channel, message: e.data.message } } }
        : room

    case 'approval_decided':
      return decide(room, e)

    case 'write_action_denied':
      return room.ticket
        ? { ...room, work: writeLocus(room.ticket) ?? room.work, ticket: { ...room.ticket, denied: { reason: e.data.reason, detail: e.data.detail } } }
        : room

    case 'write_action_done': {
      const key = connectorKey(e.data.connector)
      let referenced = false
      const lines = (room.ticket?.lines ?? []).map((line): TicketLine => {
        if (referenced || line.reference || line.connector !== key || line.operation !== e.data.operation) return line
        referenced = true
        return { ...line, reference: e.data.external_reference, writtenAt: e.at }
      })
      return {
        ...room,
        work: { at: 'write', connector: key },
        ticket: room.ticket ? { ...room.ticket, lines } : room.ticket,
        phase: room.phase.name === 'acting' ? room.phase : { name: 'acting' },
      }
    }

    case 'run_succeeded':
      return {
        ...room,
        work: DONE,
        phase: { name: 'succeeded', outcome: e.data.outcome },
        agents: room.agents.map((seated) => (seated.status === 'working' ? { ...seated, status: 'done' } : seated)),
      }

    case 'run_rejected': {
      const declined = room.approval?.steps.find((candidate) => candidate.state.is === 'declined')?.state
      const by = declined && declined.is === 'declined' ? declined.by : user(e.data.by, e.data.by)
      return { ...room, work: GATE, phase: { name: 'rejected', by, step: e.data.step } }
    }

    case 'run_failed':
      return {
        ...room,
        work: failedWork(room, e.data.stage),
        phase: { name: 'failed', stage: e.data.stage, reason: e.data.reason, retryable: e.data.retryable, message: e.data.message },
      }

    case 'run_retried':
      if (e.data.leg === 'work') {
        return { ...room, attempt: e.data.attempt, agents: [], work: START, phase: { name: 'working' }, finding: null, ticket: null, approval: null }
      }
      return {
        ...room,
        attempt: e.data.attempt,
        work: writeLocus(room.ticket) ?? room.work,
        phase: { name: 'acting' },
        ticket: room.ticket ? { ...room.ticket, denied: null } : null,
      }
  }
}

/** The open approval step, if the run is waiting for a person. Every waiting counter reads this. */
export function openStep(room: RoomState): OpenStep | null {
  for (const step of room.approval?.steps ?? []) {
    if (step.state.is === 'open') return { ...step, state: step.state }
  }
  return null
}

export function isSettled(room: RoomState): boolean {
  return room.phase.name === 'succeeded' || room.phase.name === 'rejected' || room.phase.name === 'failed'
}

// ---- spine ----

export type StationState =
  | { readonly is: 'not_reached' }
  | { readonly is: 'working' }
  | { readonly is: 'waiting'; readonly since: RunTime }
  | { readonly is: 'done' }
  | { readonly is: 'approved'; readonly by: readonly UserRef[] }
  | { readonly is: 'declined'; readonly by: UserRef }
  | { readonly is: 'failed' }
  | { readonly is: 'not_needed' }

export interface Station {
  readonly block: BlockView
  readonly state: StationState
}

function agentStation(room: RoomState): StationState {
  switch (room.phase.name) {
    case 'empty':
    case 'pending':
      return { is: 'not_reached' }
    case 'working':
      return { is: 'working' }
    case 'failed':
      return room.phase.stage === 'pending' || room.phase.stage === 'working' ? { is: 'failed' } : { is: 'done' }
    default:
      return { is: 'done' }
  }
}

function approvalStation(room: RoomState): StationState {
  if (room.phase.name === 'succeeded' && room.phase.outcome === 'nothing_to_write') return { is: 'not_needed' }
  const steps = room.approval?.steps ?? []
  const declined = steps.find((step) => step.state.is === 'declined')?.state
  if (declined?.is === 'declined') return { is: 'declined', by: declined.by }
  const open = openStep(room)
  if (open) return { is: 'waiting', since: open.state.since }
  if (steps.length > 0 && steps.every((step) => step.state.is === 'approved')) {
    return { is: 'approved', by: steps.flatMap((step) => (step.state.is === 'approved' ? [step.state.by] : [])) }
  }
  return { is: 'not_reached' }
}

function writeStation(room: RoomState): StationState {
  if (room.phase.name === 'succeeded' && room.phase.outcome === 'nothing_to_write') return { is: 'not_needed' }
  if (room.ticket?.denied) return { is: 'failed' }
  if (room.phase.name === 'failed') return room.phase.stage === 'acting' ? { is: 'failed' } : { is: 'not_reached' }
  if (room.ticket && room.ticket.lines.length > 0 && room.ticket.lines.every((line) => line.reference)) return { is: 'done' }
  if (room.phase.name === 'acting') return { is: 'working' }
  return { is: 'not_reached' }
}

/** Per-block state for the spine, mapped by block kind: the contract carries no block key on events. */
export function spineStations(room: RoomState, blocks: readonly BlockView[]): readonly Station[] {
  return blocks.map((block) => {
    switch (block.kind) {
      case 'agent':
        return { block, state: agentStation(room) }
      case 'approval':
        return { block, state: approvalStation(room) }
      case 'write_action':
        return { block, state: writeStation(room) }
    }
  })
}
