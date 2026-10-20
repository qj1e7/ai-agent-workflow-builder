import type { Actor, BlockView, FailureReason, FailureStage, RunOutcome, Verdict } from '../api/types'
import type { EventOf, RunEvent } from '../stream/parse'

type DeniedReason = EventOf<'write_action_denied'>['data']['reason']
import { agentId, doorKey, userId, type AgentId, type DoorKey, type RunTime, type Seq, type UserId } from './brand'
import { ruleOf } from './kinds'

/** What the agent registry (src/ui/agents.ts) tells the engine. A port, not an import. */
export interface AgentRef {
  readonly id: AgentId
  readonly display: string
}

export interface AgentRegistry {
  readonly host: AgentRef
  readonly troubleshooter: AgentRef
  lookup(id: AgentId): { readonly display: string; readonly readDoor: DoorKey | null }
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
/** "Speaking" is not stored: it is the current beat's `speak` move. */
export type AgentStatus = 'present' | 'working' | 'done' | 'stopped'

export interface AgentSeat {
  readonly id: AgentId
  readonly display: string
  readonly role: AgentRole
  /** 0 is the host's centre seat. Others take the lowest free slot from 1 on arrival and keep it until they leave. */
  readonly slot: number
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

export type Checker = 'locked' | 'allowed' | 'blocked'

export type Door =
  | { readonly side: 'read'; readonly key: DoorKey }
  | { readonly side: 'write'; readonly key: DoorKey; readonly checker: Checker }
  | { readonly side: 'teams' }

/** A request from an agent to its read door for one agent step. */
export interface Trip {
  readonly agent: AgentId
  readonly step: string
  readonly door: DoorKey
  /** Messages the agent sent while the step was open, drawn as 1, 2, 3 on the path. */
  readonly marks: number
  readonly state: 'out' | 'back' | 'failed'
}

export interface TicketLine {
  readonly connector: DoorKey
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

/** Where a travelling object starts or lands, and where the light can sit. Resolved to pixels by RoomLayout.point(). */
export type Anchor =
  | { readonly at: 'agent'; readonly id: AgentId }
  | { readonly at: 'starter' }
  | { readonly at: 'step'; readonly index: number }
  | { readonly at: 'door'; readonly key: DoorKey }
  | { readonly at: 'teams' }
  | { readonly at: 'table' }
  | { readonly at: 'table_edge' }

export interface Light {
  readonly on: Anchor
  readonly tone: 'act' | 'wait' | 'fail'
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
  /** The Teams door from the start, read doors as agents with a registry door arrive, write doors as proposals name connectors. */
  readonly doors: readonly Door[]
  /** Current attempt only. A retry clears them; history stays in the tape. */
  readonly trips: readonly Trip[]
  readonly ticket: Ticket | null
  /** Set by agent_message; cleared whenever the phase changes. */
  readonly speech: Speech | null
  readonly caption: Caption | null
  readonly light: Light | null
}

/** What changed hands in one event, in domain words, for the beat to animate. */
export type Move =
  | { readonly type: 'open_room' }
  | { readonly type: 'arrive'; readonly who: Anchor }
  | { readonly type: 'leave'; readonly who: Anchor }
  /** The light moves and the working ring starts; nothing travels. */
  | { readonly type: 'focus'; readonly who: Anchor }
  | { readonly type: 'carry'; readonly token: 'request' | 'message' | 'ticket'; readonly from: Anchor; readonly to: Anchor }
  | {
      readonly type: 'speak'
      readonly who: Anchor
      /** The numbered mark this message lands on its open trip's path. */
      readonly mark: { readonly agent: AgentId; readonly step: string; readonly n: number } | null
    }
  | { readonly type: 'dim'; readonly to: Anchor }
  | { readonly type: 'decide'; readonly step: number; readonly verdict: Verdict }
  | { readonly type: 'deliver'; readonly door: DoorKey; readonly reference: string }
  | { readonly type: 'fault'; readonly at: Anchor }
  | { readonly type: 'settle' }

export const EMPTY_ROOM: RoomState = {
  cursor: 0,
  startedAt: null,
  attempt: 1,
  phase: { name: 'empty' },
  starter: null,
  agents: [],
  approval: null,
  doors: [],
  trips: [],
  ticket: null,
  speech: null,
  caption: null,
  light: null,
}

export interface Fold {
  readonly room: RoomState
  readonly move: Move | null
}

const agentAnchor = (id: AgentId): Anchor => ({ at: 'agent', id })
const doorAnchor = (key: DoorKey): Anchor => ({ at: 'door', key })
const TABLE: Anchor = { at: 'table' }
const TABLE_EDGE: Anchor = { at: 'table_edge' }
const TEAMS: Anchor = { at: 'teams' }
const STARTER: Anchor = { at: 'starter' }

function lowestFreeSlot(agents: readonly AgentSeat[]): number {
  const taken = new Set(agents.map((seat) => seat.slot))
  let slot = 1
  while (taken.has(slot)) slot += 1
  return slot
}

/** Seats an agent if it is not seated. A re-join (`rejoin`) also brings it back to present, so attempt 2 starts clean. */
function seatAgent(room: RoomState, ref: AgentRef, role: AgentRole, registry: AgentRegistry, rejoin = false): RoomState {
  const seated = room.agents.find((seat) => seat.id === ref.id)
  if (seated) {
    if (!rejoin || seated.status === 'present') return room
    return { ...room, agents: room.agents.map((seat) => (seat.id === ref.id ? { ...seat, status: 'present' } : seat)) }
  }
  const slot = role === 'host' ? 0 : lowestFreeSlot(room.agents)
  const seat: AgentSeat = { id: ref.id, display: ref.display, role, slot, status: 'present' }
  const door = registry.lookup(ref.id).readDoor
  const doors = door && !room.doors.some((d) => d.side === 'read' && d.key === door) ? [...room.doors, { side: 'read' as const, key: door }] : room.doors
  return { ...room, agents: [...room.agents, seat], doors }
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

function openTripOf(room: RoomState, agent: AgentId): Trip | undefined {
  return room.trips.findLast((trip) => trip.agent === agent && trip.state === 'out')
}

function replaceTrip(trips: readonly Trip[], next: Trip): Trip[] {
  const index = trips.findIndex((trip) => trip.agent === next.agent && trip.step === next.step)
  return index < 0 ? [...trips, next] : trips.map((trip, i) => (i === index ? next : trip))
}

function setCheckers(doors: readonly Door[], checker: Checker, only?: ReadonlySet<DoorKey>): Door[] {
  return doors.map((door) =>
    door.side === 'write' && (!only || only.has(door.key)) ? { ...door, checker } : door,
  )
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
  const decidedAnchor: Anchor = { at: 'step', index: e.data.step }
  if (verdict === 'decline') {
    return { ...room, approval: { ...room.approval, steps }, light: { on: decidedAnchor, tone: 'act' } }
  }
  const next = steps.find((step) => step.state.is === 'waiting')
  if (next) {
    steps = steps.map((step) => (step === next ? { ...step, state: { is: 'open', since: e.at } } : step))
    return {
      ...room,
      approval: { ...room.approval, steps },
      light: { on: { at: 'step', index: next.index }, tone: 'wait' },
    }
  }
  const allApproved = steps.every((step) => step.state.is === 'approved')
  return {
    ...room,
    approval: { ...room.approval, steps },
    phase: allApproved ? { name: 'acting' } : room.phase,
    light: { on: decidedAnchor, tone: 'act' },
  }
}

/**
 * The fold. Pure and total: an event the state does not expect (a decision with no approval open)
 * changes only cursor and caption. Never throws on server data; parseEvent already checked shapes.
 */
export function applyEvent(room: RoomState, e: RunEvent, registry: AgentRegistry): Fold {
  const story = ruleOf(e).tier === 'story'
  const base: RoomState = {
    ...room,
    cursor: e.seq,
    caption: story ? { seq: e.seq, summary: e.summary, actor: e.actor } : room.caption,
  }
  const folded = step(base, e, registry)
  const phaseChanged = folded.room.phase.name !== room.phase.name
  return phaseChanged && folded.room.speech === room.speech ? { ...folded, room: { ...folded.room, speech: null } } : folded
}

function step(room: RoomState, e: RunEvent, registry: AgentRegistry): Fold {
  switch (e.kind) {
    case 'opaque':
    case 'leg_dispatched':
    case 'step_started':
    case 'step_finished':
    case 'step_retried':
      return { room, move: null }

    case 'run_created': {
      const started: RoomState = {
        ...room,
        startedAt: e.at,
        phase: { name: 'pending' },
        starter: user(e.data.started_by, e.actor.display),
        doors: room.doors.some((door) => door.side === 'teams') ? room.doors : [...room.doors, { side: 'teams' }],
        light: { on: STARTER, tone: 'act' },
      }
      return { room: seatAgent(started, registry.host, 'host', registry), move: { type: 'open_room' } }
    }

    case 'agent_joined': {
      const guest: AgentRef = { id: agentId(e.data.agent.id), display: e.data.agent.display }
      let next = seatAgent(room, registry.host, 'host', registry)
      next = seatAgent(next, guest, 'specialist', registry, true)
      return {
        room: {
          ...next,
          phase: next.phase.name === 'pending' || next.phase.name === 'empty' ? { name: 'working' } : next.phase,
          light: { on: agentAnchor(guest.id), tone: 'act' },
        },
        move: { type: 'arrive', who: agentAnchor(guest.id) },
      }
    }

    case 'agent_step_started': {
      const agent = actorRef(e.actor)
      let next = withStatus(seatAgent(room, agent, 'specialist', registry), agent.id, 'working')
      if (next.phase.name === 'pending') next = { ...next, phase: { name: 'working' } }
      const door = registry.lookup(agent.id).readDoor
      next = { ...next, light: { on: agentAnchor(agent.id), tone: 'act' } }
      if (!door) return { room: next, move: { type: 'focus', who: agentAnchor(agent.id) } }
      const trip: Trip = { agent: agent.id, step: e.data.step, door, marks: 0, state: 'out' }
      return {
        room: { ...next, trips: replaceTrip(next.trips, trip) },
        move: { type: 'carry', token: 'request', from: agentAnchor(agent.id), to: doorAnchor(door) },
      }
    }

    case 'agent_step_finished': {
      const agent = actorRef(e.actor)
      const next = withStatus(seatAgent(room, agent, 'specialist', registry), agent.id, 'done')
      const trip = next.trips.find((candidate) => candidate.agent === agent.id && candidate.step === e.data.step)
      if (!trip) return { room: next, move: { type: 'focus', who: agentAnchor(agent.id) } }
      return {
        room: { ...next, trips: replaceTrip(next.trips, { ...trip, state: 'back' }) },
        move: { type: 'carry', token: 'request', from: doorAnchor(trip.door), to: agentAnchor(agent.id) },
      }
    }

    case 'agent_failed': {
      const agent = actorRef(e.actor)
      const next = withStatus(seatAgent(room, agent, 'specialist', registry), agent.id, 'stopped')
      const trip = e.data.step
        ? next.trips.find((candidate) => candidate.agent === agent.id && candidate.step === e.data.step)
        : openTripOf(next, agent.id)
      const lit: RoomState = { ...next, light: { on: agentAnchor(agent.id), tone: 'fail' } }
      if (!trip) return { room: lit, move: { type: 'fault', at: agentAnchor(agent.id) } }
      return {
        room: { ...lit, trips: replaceTrip(lit.trips, { ...trip, state: 'failed' }) },
        move: { type: 'fault', at: doorAnchor(trip.door) },
      }
    }

    case 'agent_message': {
      const speaker: AgentRef = { id: agentId(e.data.speaker.id), display: e.data.speaker.display }
      const next = seatAgent(room, speaker, 'specialist', registry)
      const to: Speech['to'] =
        e.data.addressee.kind === 'agent'
          ? { kind: 'agent', id: agentId(e.data.addressee.id), display: e.data.addressee.display }
          : { kind: 'room' }
      const speech: Speech = { seq: e.seq, speaker: speaker.id, to, text: e.data.text }
      const trip = openTripOf(next, speaker.id)
      const marked = trip ? { ...trip, marks: trip.marks + 1 } : null
      return {
        room: {
          ...next,
          speech,
          trips: marked ? replaceTrip(next.trips, marked) : next.trips,
          light: { on: agentAnchor(speaker.id), tone: 'act' },
        },
        move: {
          type: 'speak',
          who: agentAnchor(speaker.id),
          mark: marked ? { agent: marked.agent, step: marked.step, n: marked.marks } : null,
        },
      }
    }

    case 'write_action_proposed': {
      const proposer = actorRef(e.actor)
      const next = seatAgent(room, proposer, 'specialist', registry)
      const lines: TicketLine[] = e.data.actions.map((action) => ({
        connector: doorKey(action.connector),
        operation: action.operation,
        line: action.line,
        reference: null,
      }))
      const doors = [...next.doors]
      for (const line of lines) {
        if (!doors.some((door) => door.side === 'write' && door.key === line.connector)) {
          doors.push({ side: 'write', key: line.connector, checker: 'locked' })
        }
      }
      return {
        room: {
          ...next,
          doors,
          ticket: { proposalId: e.data.proposal_id, digest: e.data.digest, proposer: proposer.id, lines, denied: null },
          phase: { name: 'proposed' },
          light: { on: TABLE, tone: 'act' },
        },
        move: { type: 'carry', token: 'ticket', from: agentAnchor(proposer.id), to: TABLE },
      }
    }

    case 'approval_requested': {
      const steps = stepsFromWire(e.data.steps, room.approval, e.at)
      const open = steps.find((candidate) => candidate.state.is === 'open')
      const teams = room.approval?.id === e.data.approval_id ? room.approval.teams : { is: 'not_posted' as const }
      const anchor: Anchor = open ? { at: 'step', index: open.index } : TABLE
      return {
        room: {
          ...room,
          approval: { id: e.data.approval_id, link: e.data.link, steps, teams },
          phase: { name: 'awaiting_approval' },
          light: { on: anchor, tone: 'wait' },
        },
        move: { type: 'dim', to: anchor },
      }
    }

    case 'approval_announced': {
      if (!room.approval) return { room, move: null }
      return {
        room: { ...room, approval: { ...room.approval, teams: { is: 'posted', channel: e.data.channel } } },
        move: { type: 'carry', token: 'message', from: TABLE, to: TEAMS },
      }
    }

    case 'approval_announce_failed': {
      if (!room.approval) return { room, move: null }
      return {
        room: {
          ...room,
          approval: { ...room.approval, teams: { is: 'failed', channel: e.data.channel, message: e.data.message } },
        },
        move: { type: 'fault', at: TEAMS },
      }
    }

    case 'approval_decided':
      return { room: decide(room, e), move: { type: 'decide', step: e.data.step, verdict: e.data.verdict } }

    case 'write_action_denied': {
      if (!room.ticket) return { room, move: null }
      const keys = new Set(room.ticket.lines.map((line) => line.connector))
      const first = room.ticket.lines[0]?.connector
      const at: Anchor = first ? doorAnchor(first) : TABLE
      return {
        room: {
          ...room,
          ticket: { ...room.ticket, denied: { reason: e.data.reason, detail: e.data.detail } },
          doors: setCheckers(room.doors, 'blocked', keys),
          light: { on: at, tone: 'fail' },
        },
        move: { type: 'fault', at },
      }
    }

    case 'write_action_done': {
      const key = doorKey(e.data.connector)
      let referenced = false
      const lines = (room.ticket?.lines ?? []).map((line) => {
        if (referenced || line.reference || line.connector !== key || line.operation !== e.data.operation) return line
        referenced = true
        return { ...line, reference: e.data.external_reference }
      })
      const doors = room.doors.some((door) => door.side === 'write' && door.key === key)
        ? room.doors
        : [...room.doors, { side: 'write' as const, key, checker: 'locked' as const }]
      return {
        room: {
          ...room,
          ticket: room.ticket ? { ...room.ticket, lines } : room.ticket,
          doors: setCheckers(doors, 'allowed', new Set([key])),
          phase: room.phase.name === 'acting' ? room.phase : { name: 'acting' },
          light: { on: doorAnchor(key), tone: 'act' },
        },
        move: { type: 'deliver', door: key, reference: e.data.external_reference },
      }
    }

    case 'run_succeeded':
      return {
        room: {
          ...room,
          phase: { name: 'succeeded', outcome: e.data.outcome },
          agents: room.agents.map((seat) => (seat.status === 'working' ? { ...seat, status: 'done' } : seat)),
          light: { on: room.ticket ? TABLE : agentAnchor(registry.host.id), tone: 'act' },
        },
        move: { type: 'settle' },
      }

    case 'run_rejected': {
      const declined = room.approval?.steps.find((candidate) => candidate.state.is === 'declined')?.state
      const by = declined && declined.is === 'declined' ? declined.by : user(e.data.by, e.data.by)
      return {
        room: { ...room, phase: { name: 'rejected', by, step: e.data.step }, light: { on: TABLE_EDGE, tone: 'act' } },
        move: { type: 'carry', token: 'ticket', from: TABLE, to: TABLE_EDGE },
      }
    }

    case 'run_failed': {
      const failed: RoomState = {
        ...room,
        phase: {
          name: 'failed',
          stage: e.data.stage,
          reason: e.data.reason,
          retryable: e.data.retryable,
          message: e.data.message,
        },
      }
      const seated = seatAgent(failed, registry.troubleshooter, 'troubleshooter', registry)
      return {
        room: { ...seated, light: { on: agentAnchor(registry.troubleshooter.id), tone: 'act' } },
        move: { type: 'arrive', who: agentAnchor(registry.troubleshooter.id) },
      }
    }

    case 'run_retried': {
      const hadTroubleshooter = room.agents.some((seat) => seat.role === 'troubleshooter')
      const agents = room.agents
        .filter((seat) => seat.role !== 'troubleshooter')
        .map((seat): AgentSeat => (seat.status === 'present' ? seat : { ...seat, status: 'present' }))
      const work = e.data.leg === 'work'
      const next: RoomState = {
        ...room,
        attempt: e.data.attempt,
        agents,
        trips: [],
        phase: work ? { name: 'working' } : { name: 'acting' },
        ticket: work ? null : room.ticket ? { ...room.ticket, denied: null } : null,
        approval: work ? null : room.approval,
        doors: setCheckers(room.doors, 'locked'),
        light: { on: room.starter && e.actor.id === room.starter.id ? STARTER : agentAnchor(registry.host.id), tone: 'act' },
      }
      return {
        room: next,
        move: hadTroubleshooter
          ? { type: 'leave', who: agentAnchor(registry.troubleshooter.id) }
          : { type: 'focus', who: next.light?.on ?? STARTER },
      }
    }
  }
}

/** The open approval step, if the room is waiting for a person. Dimming, the amber light and every waiting counter read this. */
export function openStep(room: RoomState): OpenStep | null {
  for (const step of room.approval?.steps ?? []) {
    if (step.state.is === 'open') return { ...step, state: step.state }
  }
  return null
}

export type TicketLife = 'draft' | 'waiting' | 'approved' | 'written' | 'denied' | 'declined'

/** Derived, not stored: stamps come from approval steps, written from line references. */
export function ticketLife(room: RoomState): TicketLife | null {
  const { ticket, approval } = room
  if (!ticket) return null
  if (ticket.denied) return 'denied'
  const steps = approval?.steps ?? []
  if (steps.some((step) => step.state.is === 'declined')) return 'declined'
  if (ticket.lines.length > 0 && ticket.lines.every((line) => line.reference)) return 'written'
  if (!approval) return 'draft'
  if (steps.some((step) => step.state.is === 'open' || step.state.is === 'waiting')) return 'waiting'
  return 'approved'
}

export interface Stamp {
  readonly verdict: Verdict
  readonly by: UserRef
}

/** The decided steps in order: the stamps on the ticket. */
export function stamps(room: RoomState): readonly Stamp[] {
  return (room.approval?.steps ?? []).flatMap((step): Stamp[] => {
    if (step.state.is === 'approved') return [{ verdict: 'approve', by: step.state.by }]
    if (step.state.is === 'declined') return [{ verdict: 'decline', by: step.state.by }]
    return []
  })
}

export function isSettled(room: RoomState): boolean {
  return room.phase.name === 'succeeded' || room.phase.name === 'rejected' || room.phase.name === 'failed'
}

// ---- floor plan ----

export type SeatKey = `agent:${string}` | 'starter' | `step:${number}`

export interface PlanDoor {
  readonly side: Door['side']
  /** null for a write door the template promises but no proposal has named yet, and 'teams' for the Teams door. */
  readonly key: DoorKey | 'teams' | null
  /** The template's block name for a seeded write door, otherwise null. */
  readonly label: string | null
}

export interface FloorPlan {
  /** Slot 0 is the host. */
  readonly agents: readonly { readonly key: SeatKey; readonly slot: number }[]
  /** Slot 0 the starter, then one seat per approval step in step order. */
  readonly people: readonly { readonly key: SeatKey; readonly slot: number }[]
  readonly doors: readonly PlanDoor[]
}

export interface ExpectedWrite {
  readonly label: string
}

export function agentSeatKey(id: AgentId): SeatKey {
  return `agent:${id}`
}

export function stepSeatKey(index: number): SeatKey {
  return `step:${index}`
}

export function seatKeyOf(a: Anchor): SeatKey | null {
  switch (a.at) {
    case 'agent':
      return agentSeatKey(a.id)
    case 'starter':
      return 'starter'
    case 'step':
      return stepSeatKey(a.index)
    default:
      return null
  }
}

/**
 * Seats and doors derive from state, so layout tests need no events. Write doors the template promises
 * (`expectedWrites`, one per write_action block) stand locked from the first second; the first proposal
 * that names a connector takes the first seeded door, so the door never jumps.
 */
export function floorPlanOf(room: RoomState, expectedWrites: readonly ExpectedWrite[] = []): FloorPlan {
  const agents = [...room.agents]
    .sort((a, b) => a.slot - b.slot)
    .map((seat) => ({ key: agentSeatKey(seat.id), slot: seat.slot }))
  const people: FloorPlan['people'] = [
    ...(room.starter ? [{ key: 'starter' as const, slot: 0 }] : []),
    ...(room.approval?.steps ?? []).map((step) => ({ key: stepSeatKey(step.index), slot: step.index + 1 })),
  ]
  const writes = room.doors.filter((door): door is Extract<Door, { side: 'write' }> => door.side === 'write')
  const doors: PlanDoor[] = []
  for (const door of room.doors) {
    if (door.side === 'teams') doors.push({ side: 'teams', key: 'teams', label: null })
    else if (door.side === 'read') doors.push({ side: 'read', key: door.key, label: null })
  }
  const count = Math.max(writes.length, expectedWrites.length)
  for (let i = 0; i < count; i += 1) {
    doors.push({ side: 'write', key: writes[i]?.key ?? null, label: expectedWrites[i]?.label ?? null })
  }
  return { agents, people, doors }
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
