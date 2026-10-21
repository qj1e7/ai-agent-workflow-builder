import type { Actor, BlockView, FailureReason, FailureStage, RunOutcome } from '../api/types'
import type { EventOf, RunEvent } from '../stream/parse'

type DeniedReason = EventOf<'write_action_denied'>['data']['reason']
import { agentId, connectorKey, userId, type AgentId, type ConnectorKey, type RunTime, type Seq, type UserId } from './brand'
import { findingItems } from './finding'
import { ruleOf } from './kinds'

/** What the agent registry (src/ui/agents.ts) tells the engine. A port, not an import. */
export interface AgentRef {
  readonly id: AgentId
  readonly display: string
}

export interface AgentRegistry {
  readonly host: AgentRef
  readonly troubleshooter: AgentRef
  lookup(id: AgentId): { readonly display: string; readonly readDoor: ConnectorKey | null }
  /** The known agent whose display name appears in the words as whole words, case-insensitive. */
  named(words: string): AgentRef | null
}

export function agentNamedIn(words: string, agents: readonly AgentRef[]): AgentRef | null {
  const lower = words.toLowerCase()
  return agents.find((agent) => new RegExp(`\\b${agent.display.toLowerCase()}\\b`).test(lower)) ?? null
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

export type AgentRole = 'host' | 'specialist' | 'troubleshooter'
export type AgentStatus = 'present' | 'working' | 'done' | 'stopped'

export interface AgentSeat {
  readonly id: AgentId
  readonly display: string
  readonly role: AgentRole
  readonly status: AgentStatus
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
}

export interface Ticket {
  readonly proposalId: string
  readonly digest: string
  readonly proposer: AgentId
  readonly lines: readonly TicketLine[]
  readonly denied: { readonly reason: DeniedReason; readonly detail: string } | null
}

export interface Speech {
  readonly seq: Seq
  readonly speaker: AgentId
  readonly to: { readonly kind: 'agent'; readonly id: AgentId; readonly display: string } | { readonly kind: 'room' }
  /** agent_message data.text, verbatim. The only words the room ever puts in an agent's mouth. */
  readonly text: string
}

export interface Caption {
  readonly seq: Seq
  /** The latest story event's summary, verbatim. */
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
  /** Join order. Seats stay when an agent finishes; only the troubleshooter ever leaves. */
  readonly agents: readonly AgentSeat[]
  readonly approval: Approval | null
  /** Set by a step that finished with a list; cleared by the proposal and by a retry of the work leg. */
  readonly finding: Finding | null
  readonly ticket: Ticket | null
  /** Set by agent_message; cleared when the phase changes or a step starts or finishes. */
  readonly speech: Speech | null
  readonly caption: Caption | null
}

export const EMPTY_ROOM: RoomState = {
  cursor: 0,
  startedAt: null,
  attempt: 1,
  phase: { name: 'empty' },
  starter: null,
  agents: [],
  approval: null,
  finding: null,
  ticket: null,
  speech: null,
  caption: null,
}

/** Seats an agent if it is not seated. A re-join (`rejoin`) also brings it back to present, so attempt 2 starts clean. */
function seatAgent(room: RoomState, ref: AgentRef, role: AgentRole, rejoin = false): RoomState {
  const seated = room.agents.find((seat) => seat.id === ref.id)
  if (seated) {
    if (!rejoin || seated.status === 'present') return room
    return { ...room, agents: room.agents.map((seat) => (seat.id === ref.id ? { ...seat, status: 'present' } : seat)) }
  }
  return { ...room, agents: [...room.agents, { id: ref.id, display: ref.display, role, status: 'present' }] }
}

function withStatus(room: RoomState, id: AgentId, status: AgentStatus): RoomState {
  return { ...room, agents: room.agents.map((seat) => (seat.id === id ? { ...seat, status } : seat)) }
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
  const allApproved = steps.every((step) => step.state.is === 'approved')
  return { ...room, approval: { ...room.approval, steps }, phase: allApproved ? { name: 'acting' } : room.phase }
}

/**
 * The fold. Pure and total: an event the state does not expect (a decision with no approval open)
 * changes only cursor and caption. Never throws on server data; parseEvent already checked shapes.
 */
export function applyEvent(room: RoomState, e: RunEvent, registry: AgentRegistry): RoomState {
  const rule = ruleOf(e)
  const base: RoomState = {
    ...room,
    cursor: e.seq,
    caption: rule.tier === 'story' && rule.caption ? { seq: e.seq, summary: e.summary, actor: e.actor } : room.caption,
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

    case 'run_created': {
      const started: RoomState = { ...room, startedAt: e.at, phase: { name: 'pending' }, starter: user(e.data.started_by, e.actor.display) }
      return seatAgent(started, registry.host, 'host')
    }

    case 'agent_joined': {
      const guest: AgentRef = { id: agentId(e.data.agent.id), display: e.data.agent.display }
      const next = seatAgent(seatAgent(room, registry.host, 'host'), guest, 'specialist', true)
      return { ...next, phase: next.phase.name === 'pending' || next.phase.name === 'empty' ? { name: 'working' } : next.phase }
    }

    case 'agent_step_started': {
      const agent = actorRef(e.actor)
      const next: RoomState = { ...withStatus(seatAgent(room, agent, 'specialist'), agent.id, 'working'), speech: null }
      return next.phase.name === 'pending' ? { ...next, phase: { name: 'working' } } : next
    }

    case 'agent_step_finished': {
      const agent = actorRef(e.actor)
      const done = withStatus(seatAgent(room, agent, 'specialist'), agent.id, 'done')
      const items = findingItems(e.data.result)
      return { ...done, finding: items.length > 0 ? { agent: agent.id, step: e.data.step, items } : done.finding, speech: null }
    }

    case 'agent_failed': {
      const agent = actorRef(e.actor)
      return withStatus(seatAgent(room, agent, 'specialist'), agent.id, 'stopped')
    }

    case 'agent_message': {
      const speaker: AgentRef = { id: agentId(e.data.speaker.id), display: e.data.speaker.display }
      const to: Speech['to'] =
        e.data.addressee.kind === 'agent'
          ? { kind: 'agent', id: agentId(e.data.addressee.id), display: e.data.addressee.display }
          : { kind: 'room' }
      return { ...seatAgent(room, speaker, 'specialist'), speech: { seq: e.seq, speaker: speaker.id, to, text: e.data.text } }
    }

    case 'write_action_proposed': {
      const proposer = actorRef(e.actor)
      const lines: TicketLine[] = e.data.actions.map((action) => ({
        connector: connectorKey(action.connector),
        operation: action.operation,
        line: action.line,
        reference: null,
      }))
      return {
        ...seatAgent(room, proposer, 'specialist'),
        finding: null,
        ticket: { proposalId: e.data.proposal_id, digest: e.data.digest, proposer: proposer.id, lines, denied: null },
        phase: { name: 'proposed' },
      }
    }

    case 'approval_requested': {
      const steps = stepsFromWire(e.data.steps, room.approval, e.at)
      const teams = room.approval?.id === e.data.approval_id ? room.approval.teams : { is: 'not_posted' as const }
      return { ...room, approval: { id: e.data.approval_id, link: e.data.link, steps, teams }, phase: { name: 'awaiting_approval' } }
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
      return room.ticket ? { ...room, ticket: { ...room.ticket, denied: { reason: e.data.reason, detail: e.data.detail } } } : room

    case 'write_action_done': {
      const key = connectorKey(e.data.connector)
      let referenced = false
      const lines = (room.ticket?.lines ?? []).map((line) => {
        if (referenced || line.reference || line.connector !== key || line.operation !== e.data.operation) return line
        referenced = true
        return { ...line, reference: e.data.external_reference }
      })
      return {
        ...room,
        ticket: room.ticket ? { ...room.ticket, lines } : room.ticket,
        phase: room.phase.name === 'acting' ? room.phase : { name: 'acting' },
      }
    }

    case 'run_succeeded':
      return {
        ...room,
        phase: { name: 'succeeded', outcome: e.data.outcome },
        agents: room.agents.map((seat) => (seat.status === 'working' ? { ...seat, status: 'done' } : seat)),
      }

    case 'run_rejected': {
      const declined = room.approval?.steps.find((candidate) => candidate.state.is === 'declined')?.state
      const by = declined && declined.is === 'declined' ? declined.by : user(e.data.by, e.data.by)
      return { ...room, phase: { name: 'rejected', by, step: e.data.step } }
    }

    case 'run_failed': {
      const failed: RoomState = {
        ...room,
        phase: { name: 'failed', stage: e.data.stage, reason: e.data.reason, retryable: e.data.retryable, message: e.data.message },
      }
      return seatAgent(failed, registry.troubleshooter, 'troubleshooter')
    }

    case 'run_retried': {
      const agents = room.agents
        .filter((seat) => seat.role !== 'troubleshooter')
        .map((seat): AgentSeat => (seat.status === 'present' ? seat : { ...seat, status: 'present' }))
      const work = e.data.leg === 'work'
      return {
        ...room,
        attempt: e.data.attempt,
        agents,
        phase: work ? { name: 'working' } : { name: 'acting' },
        finding: work ? null : room.finding,
        ticket: work ? null : room.ticket ? { ...room.ticket, denied: null } : null,
        approval: work ? null : room.approval,
      }
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
