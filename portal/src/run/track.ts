import { connectorLabel, connectorNamedIn, objectNoun } from '../api/labels'
import type { BlockView, FailureReason, Verdict } from '../api/types'
import { connectorKey, type AgentId, type ConnectorKey, type Ms, type RunTime, type Seq, type UserId } from './brand'
import { splitActionLine } from './describe'
import { EMPTY_ROOM, openStep, type AgentSeat, type AgentStatus, type ApprovalStep, type Locus, type RoomState, type TicketLine, type UserRef } from './room'

/** One frame as the Tracker sees it: the folded state plus the two clock facts the gate shows. */
export interface Scene {
  readonly room: RoomState
  /** The open step's wait, from the director: honest live, in replay and in a hold. */
  readonly waiting: { readonly since: RunTime; readonly elapsedMs: Ms } | null
  /** A counter on screen moves faster than the wall: the demo's squeezed wait, or a replay hold. Never the viewer's 2x. */
  readonly spedUp: boolean
}

export const IDLE_SCENE: Scene = { room: EMPTY_ROOM, waiting: null, spedUp: false }

export type StopKind = 'start' | 'agent' | 'draft' | 'gate' | 'write' | 'done'

/** Stable while the stop exists, so a proposal that claims a seeded write stop remounts nothing. */
export type StopKey = 'start' | 'draft' | 'gate' | 'done' | `agent:${string}` | `write:${string}`

export type StopState =
  | 'passed'
  | 'current'
  | 'future'
  /** The line broke here. */
  | 'failed'
  /** The Done stop of a succeeded run. */
  | 'done'
  /** Nothing to write, or a seeded write stop the proposal does not use. */
  | 'not_needed'

export interface Stop {
  readonly key: StopKey
  readonly kind: StopKind
  /** The block name, the connector label, 'Draft <noun>', or the fixed 'Started', 'Done' and stand-in names. */
  readonly name: string
  readonly state: StopState
  readonly caption: StopCaption
  /** Who stands over this stop, in a stable order. */
  readonly cast: readonly Figure[]
}

/** A few short items show as chips; anything else is one count chip. */
export type Items = { readonly is: 'chips'; readonly items: readonly string[] } | { readonly is: 'count'; readonly count: number }

/** The parcel is one column wide, so it carries fewer chips than the caption under a stop, which may wrap. */
export const PARCEL_CHIPS = 2
export const CAPTION_CHIPS = 3
export const CHIP_CHARS = 32

export type WriteStatus = 'not_yet' | 'writing' | 'written' | 'blocked' | 'none_written'

export type StopCaption =
  | { readonly is: 'none' }
  /** Started: the run's start. */
  | { readonly is: 'time'; readonly at: RunTime }
  /** An agent stop's latest running step. */
  | { readonly is: 'step'; readonly step: string; readonly summary: string }
  | { readonly is: 'found'; readonly items: Items }
  | { readonly is: 'stopped'; readonly step: string | null; readonly errorType: string | null; readonly reason: FailureReason | null }
  | { readonly is: 'needs_person' }
  | { readonly is: 'waiting'; readonly elapsedMs: Ms; readonly spedUp: boolean }
  | { readonly is: 'approved'; readonly by: readonly string[] }
  | { readonly is: 'declined'; readonly by: string }
  | { readonly is: 'write'; readonly status: WriteStatus; readonly references: readonly string[] }
  | { readonly is: 'not_needed' }

export type Figure =
  | {
      readonly key: `person:${string}`
      readonly is: 'person'
      readonly id: UserId
      readonly name: string
      readonly acting: boolean
      /** Set for an approver who decided. Null for the starter. */
      readonly verdict: Verdict | null
    }
  | {
      readonly key: `agent:${string}`
      readonly is: 'agent'
      readonly id: AgentId
      readonly name: string
      readonly acting: boolean
      readonly status: AgentStatus
    }
  | {
      /** An approval step nobody has decided yet. open: the step waiting now; later steps stay locked. */
      readonly key: `seat:${number}`
      readonly is: 'seat'
      readonly step: number
      readonly label: string
      readonly open: boolean
    }

export type ParcelForm =
  | { readonly is: 'request' }
  | { readonly is: 'found'; readonly items: Items }
  /** noun is '' when the proposal writes more than one kind of thing. */
  | { readonly is: 'draft'; readonly noun: string; readonly count: number }
  /** One written key as it is; several as their count. The written panel lists every key. */
  | { readonly is: 'written'; readonly references: Items }
  | { readonly is: 'declined' }
  | { readonly is: 'stopped' }

export interface Parcel {
  /** Index into stops. */
  readonly at: number
  /** Waits in front of the stop's node rather than on it: at the gate, in front of the barrier. */
  readonly before: boolean
  readonly form: ParcelForm
}

export type GateState = 'idle' | 'waiting' | 'open' | 'declined' | 'not_needed'

export interface Gate {
  readonly stop: number
  readonly state: GateState
  readonly approvalId: string | null
  /** approval_requested.data.link: the approval page, which the Teams card also opens. */
  readonly link: string | null
  readonly openStep: number | null
  /** The Teams post failed, so the approval page link is the way to reach an Approver. */
  readonly teamsFailed: boolean
}

export interface Speech {
  readonly seq: Seq
  readonly stop: number
  readonly speaker: AgentId
  readonly name: string
  /** agent_message text, verbatim. */
  readonly text: string
}

export interface WrittenLine {
  readonly connector: ConnectorKey
  readonly reference: string
  /** The action line's title part, from the stream. */
  readonly title: string
  readonly at: RunTime | null
}

/** Where a panel opens. The model places it; the panel fetches its own content. */
export type PanelSpot =
  | { readonly is: 'approval'; readonly stop: number; readonly approvalId: string; readonly step: number }
  | { readonly is: 'trouble'; readonly stop: number; readonly retryable: boolean; readonly attempt: number }
  | { readonly is: 'written'; readonly stop: number; readonly lines: readonly WrittenLine[]; readonly approvedBy: readonly string[] }

export type Headline =
  | { readonly is: 'not_started' }
  | { readonly is: 'starting' }
  /** agent: who reported the latest step, or before any step the latest specialist to join. Null before anyone joins. */
  | { readonly is: 'working'; readonly agent: AgentId | null }
  | { readonly is: 'found'; readonly step: string; readonly count: number }
  | { readonly is: 'drafting'; readonly noun: string; readonly count: number }
  | { readonly is: 'waiting' }
  /** Approved, and nothing written yet. */
  | { readonly is: 'approved'; readonly by: readonly string[] }
  | { readonly is: 'written'; readonly lines: readonly { readonly reference: string; readonly connector: ConnectorKey }[] }
  | { readonly is: 'nothing_to_write' }
  | { readonly is: 'declined'; readonly by: string }
  | { readonly is: 'stopped' }

export interface Track {
  readonly stops: readonly Stop[]
  /** Null before run_created. */
  readonly parcel: Parcel | null
  /** Null for a use case with no approval. */
  readonly gate: Gate | null
  readonly breakAt: number | null
  /** The rail past the parcel is dashed: the run broke or was declined, so the rest will not happen. */
  readonly cut: boolean
  readonly speech: Speech | null
  readonly panel: PanelSpot | null
  readonly headline: Headline
  /** The latest captioned story event's summary, verbatim. */
  readonly subline: string
  readonly attempt: number
}

export interface CastLayout {
  readonly size: 'full' | 'compact'
  /** Figures drawn; the rest show as one "+N" figure. */
  readonly shown: number
  readonly more: number
}

/** Full size for up to two figures on a stop, compact from three; above four, three show and a "+N". */
export function castLayout(count: number): CastLayout {
  const size = count <= 2 ? 'full' : 'compact'
  return count > 4 ? { size, shown: 3, more: count - 3 } : { size, shown: count, more: 0 }
}

export function itemsOf(items: readonly string[], limit: number): Items {
  return items.length <= limit && items.every((item) => item.length <= CHIP_CHARS) ? { is: 'chips', items } : { is: 'count', count: items.length }
}

/** The line for a use case with nothing done: the first screen. */
export function planTrack(blocks: readonly BlockView[]): Track {
  return trackOf(IDLE_SCENE, blocks)
}

interface LineStop {
  readonly key: StopKey
  readonly kind: StopKind
  readonly name: string
  readonly block: BlockView | null
  /** Write stops: the connector, once the block's name or the proposal names one. */
  readonly connector: ConnectorKey | null
  /** A seeded write stop the proposal does not use. */
  readonly unclaimed: boolean
}

const FLOW: Readonly<Record<StopKind, number>> = { start: 0, agent: 1, draft: 2, gate: 3, write: 4, done: 5 }

function lineStop(key: StopKey, kind: StopKind, name: string, block: BlockView | null = null): LineStop {
  return { key, kind, name, block, connector: null, unclaimed: false }
}

function unique<T>(values: readonly T[]): T[] {
  return [...new Set(values)]
}

/**
 * Started, the agent stops, Draft when a write is expected, the gate when an approval is, the write stops, Done.
 * Flow order, not block order: the platform runs agents, then the proposal, the approval and the writes. Events
 * the blocks do not foresee get a stand-in stop, so nothing that happened is dropped.
 */
function lineOf(blocks: readonly BlockView[], room: RoomState): LineStop[] {
  const agentBlocks = blocks.filter((block) => block.kind === 'agent')
  const approvalBlock = blocks.find((block) => block.kind === 'approval')
  const agentWork = room.agents.length > 0 || room.work.at === 'agents' || room.work.at === 'agent' || room.finding !== null
  const agents =
    agentBlocks.length > 0
      ? agentBlocks.map((block) => lineStop(`agent:${block.key}`, 'agent', block.name, block))
      : agentWork
        ? [lineStop('agent:work', 'agent', 'Work')]
        : []
  const writeBlocks = blocks.filter((block) => block.kind === 'write_action')
  const writes = writeStopsOf(writeBlocks, room.ticket)
  const draft = writes.length > 0 || room.ticket ? [lineStop('draft', 'draft', draftName(writeBlocks, room.ticket))] : []
  const gate = approvalBlock || room.approval ? [lineStop('gate', 'gate', approvalBlock?.name ?? 'Approval')] : []
  return [lineStop('start', 'start', 'Started'), ...agents, ...draft, ...gate, ...writes, lineStop('done', 'done', 'Done')]
}

/**
 * Before a proposal, one stop per write block, keyed by the connector its name names, else by its block key.
 * After it, the proposal's connectors in action order. Each claims the seeded stop with its connector, else the
 * first seeded stop with none, keeping that stop's key; a connector with no seeded stop gets a new one. Seeded
 * stops nobody claims stay as unclaimed. When blocks and proposal agree, keys and places do not move.
 */
function writeStopsOf(writeBlocks: readonly BlockView[], ticket: RoomState['ticket']): LineStop[] {
  const taken = new Set<StopKey>()
  const keyFor = (wanted: `write:${string}`): StopKey => {
    let key = wanted
    for (let n = 2; taken.has(key); n += 1) key = `${wanted}~${n}`
    taken.add(key)
    return key
  }
  const seeded = writeBlocks.map((block): LineStop => {
    const named = connectorNamedIn(block.name)
    const connector = named === null ? null : connectorKey(named)
    return { key: keyFor(`write:${connector ?? block.key}`), kind: 'write', name: connector ? connectorLabel(connector) : block.name, block, connector, unclaimed: false }
  })
  if (!ticket) return seeded
  const free = [...seeded]
  const claimed = unique(ticket.lines.map((line) => line.connector)).map((connector): LineStop => {
    const same = free.findIndex((stop) => stop.connector === connector)
    const index = same >= 0 ? same : free.findIndex((stop) => stop.connector === null)
    const [seed] = index >= 0 ? free.splice(index, 1) : []
    const name = connectorLabel(connector)
    return seed ? { ...seed, name, connector } : { key: keyFor(`write:${connector}`), kind: 'write', name, block: null, connector, unclaimed: false }
  })
  return [...claimed, ...free.map((stop) => ({ ...stop, unclaimed: true }))]
}

/** The noun every expected write shares, or '' when they differ or have none. */
function nounOf(operations: readonly string[]): string {
  const nouns = unique(operations.map(objectNoun).filter((noun) => noun !== ''))
  return nouns.length === 1 ? (nouns[0] ?? '') : ''
}

/** 'Draft ticket', 'Draft tickets' for more than one, else 'Draft'. Before a proposal the write blocks' keys stand in. */
function draftName(writeBlocks: readonly BlockView[], ticket: RoomState['ticket']): string {
  const operations = ticket ? ticket.lines.map((line) => line.operation) : writeBlocks.map((block) => block.key)
  const noun = nounOf(operations)
  return noun === '' ? 'Draft' : `Draft ${noun}${operations.length > 1 ? 's' : ''}`
}

function namesIn(words: string, name: string): boolean {
  if (name.trim() === '') return false
  const escaped = name.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`\\b${escaped}\\b`, 'i').test(words)
}

/**
 * Each specialist's agent stop, in join order: the agent block whose name or description names it as whole words
 * while no earlier agent stands there, else the next agent block no one has claimed; the last agent stop takes the
 * rest. Seats only append within an attempt, so an agent keeps the home it was first given. The host has no home.
 */
function homesOf(agents: readonly AgentSeat[], line: readonly LineStop[]): ReadonlyMap<AgentId, number> {
  const agentStops = line.flatMap((stop, index) => (stop.kind === 'agent' ? [{ stop, index }] : []))
  const last = agentStops.at(-1)
  const homes = new Map<AgentId, number>()
  if (!last) return homes
  const claimed = new Set<number>()
  for (const seat of agents) {
    if (seat.role !== 'specialist') continue
    const free = agentStops.filter(({ index }) => !claimed.has(index))
    const named = free.find(({ stop }) => stop.block !== null && namesIn(`${stop.block.name} ${stop.block.description}`, seat.display))
    const home = named ?? free[0] ?? last
    claimed.add(home.index)
    homes.set(seat.id, home.index)
  }
  return homes
}

function kindOf(locus: Locus): StopKind {
  switch (locus.at) {
    case 'agents':
    case 'agent':
      return 'agent'
    default:
      return locus.at
  }
}

/** The stop a locus stands on. A locus whose stop the line lacks falls back to the nearest stop before it in flow. */
function stopOf(locus: Locus, line: readonly LineStop[], homes: ReadonlyMap<AgentId, number>): number {
  const exact = exactStopOf(locus, line, homes)
  if (exact >= 0) return exact
  const flow = FLOW[kindOf(locus)]
  return Math.max(0, line.findLastIndex((stop) => FLOW[stop.kind] < flow))
}

function exactStopOf(locus: Locus, line: readonly LineStop[], homes: ReadonlyMap<AgentId, number>): number {
  switch (locus.at) {
    case 'agent':
      return homes.get(locus.id) ?? line.findIndex((stop) => stop.kind === 'agent')
    case 'agents':
      return line.findIndex((stop) => stop.kind === 'agent')
    case 'write':
      return line.findIndex((stop) => stop.kind === 'write' && stop.connector === locus.connector)
    default:
      return line.findIndex((stop) => stop.kind === locus.at)
  }
}

function declinedBy(steps: readonly ApprovalStep[]): UserRef | null {
  for (const step of steps) if (step.state.is === 'declined') return step.state.by
  return null
}

function references(lines: readonly TicketLine[]): string[] {
  return lines.flatMap((line) => (line.reference === null ? [] : [line.reference]))
}

function gateStateOf(steps: readonly ApprovalStep[], nothingToWrite: boolean): GateState {
  if (steps.length === 0) return nothingToWrite ? 'not_needed' : 'idle'
  if (declinedBy(steps)) return 'declined'
  return steps.every((step) => step.state.is === 'approved') ? 'open' : 'waiting'
}

function approvers(steps: readonly ApprovalStep[]): string[] {
  return steps.flatMap((step) => (step.state.is === 'approved' ? [step.state.by.display] : []))
}

function stepFigure(step: ApprovalStep, actingId: string | null): Figure {
  const state = step.state
  if (state.is === 'approved' || state.is === 'declined') {
    return {
      key: `person:${state.by.id}`,
      is: 'person',
      id: state.by.id,
      name: state.by.display,
      acting: state.by.id === actingId,
      verdict: state.is === 'approved' ? 'approve' : 'decline',
    }
  }
  return { key: `seat:${step.index}`, is: 'seat', step: step.index, label: step.label, open: state.is === 'open' }
}

/**
 * Everything the line draws, from one frame and the use case's blocks. Pure and total: blocks that name no agent,
 * a proposal that disagrees with the blocks, an approval with two steps and a finding of 312 items all give a line.
 */
export function trackOf(scene: Scene, blocks: readonly BlockView[]): Track {
  const { room } = scene
  const { phase, ticket } = room
  const steps = room.approval?.steps ?? []
  const line = lineOf(blocks, room)
  const homes = homesOf(room.agents, line)
  const place = (locus: Locus) => stopOf(locus, line, homes)
  const current = phase.name === 'empty' ? null : place(room.work)
  const nothingToWrite = phase.name === 'succeeded' && phase.outcome === 'nothing_to_write'
  const decliner = phase.name === 'rejected' ? phase.by : declinedBy(steps)

  const stopped = room.agents.find((seat) => seat.status === 'stopped')
  const breakAt =
    stopped && (phase.name === 'working' || phase.name === 'failed')
      ? place(stopped.at)
      : ticket?.denied || phase.name === 'failed'
        ? current
        : null
  const cut = breakAt !== null || decliner !== null

  const latestSeq = room.latest?.seq ?? 0
  const actingId = room.speech && room.speech.seq > latestSeq ? room.speech.speaker : (room.latest?.actor.id ?? null)
  const linesAt = (connector: ConnectorKey | null) => (ticket?.lines ?? []).filter((candidate) => candidate.connector === connector)

  function stateOf(stop: LineStop, index: number): StopState {
    if (index === breakAt) return 'failed'
    if (stop.kind === 'done' && phase.name === 'succeeded') return 'done'
    if (stop.unclaimed || (nothingToWrite && (stop.kind === 'draft' || stop.kind === 'gate' || stop.kind === 'write'))) return 'not_needed'
    if (current === null || index > current) return 'future'
    return index < current ? 'passed' : 'current'
  }

  function agentCaption(index: number): StopCaption {
    if (index === breakAt) {
      const here = stopped && place(stopped.at) === index ? stopped.step : null
      return { is: 'stopped', step: here?.step ?? null, errorType: here?.errorType ?? null, reason: phase.name === 'failed' ? phase.reason : null }
    }
    if (room.finding && place({ at: 'agent', id: room.finding.agent }) === index) return { is: 'found', items: itemsOf(room.finding.items, CAPTION_CHIPS) }
    let running: { readonly step: string; readonly summary: string; readonly seq: number } | null = null
    for (const seat of room.agents) {
      const step = seat.step
      if (step?.state !== 'running' || step.step === null || place(seat.at) !== index) continue
      if (!running || step.seq > running.seq) running = { step: step.step, summary: step.summary, seq: step.seq }
    }
    return running ? { is: 'step', step: running.step, summary: running.summary } : { is: 'none' }
  }

  function gateCaption(): StopCaption {
    if (nothingToWrite) return { is: 'not_needed' }
    const declined = declinedBy(steps)
    if (declined) return { is: 'declined', by: declined.display }
    if (openStep(room)) return { is: 'waiting', elapsedMs: scene.waiting?.elapsedMs ?? 0, spedUp: scene.spedUp }
    if (steps.length > 0 && steps.every((step) => step.state.is === 'approved')) return { is: 'approved', by: approvers(steps) }
    return { is: 'needs_person' }
  }

  function writeCaption(stop: LineStop, index: number): StopCaption {
    if (stop.unclaimed || nothingToWrite) return { is: 'not_needed' }
    const lines = linesAt(stop.connector)
    const written = references(lines)
    if (lines.length > 0 && written.length === lines.length) return { is: 'write', status: 'written', references: written }
    if (index === breakAt && ticket?.denied) return { is: 'write', status: 'blocked', references: written }
    if (cut) return { is: 'write', status: written.length > 0 ? 'written' : 'none_written', references: written }
    if (index === current && phase.name === 'acting') return { is: 'write', status: 'writing', references: written }
    return { is: 'write', status: 'not_yet', references: written }
  }

  function captionOf(stop: LineStop, index: number): StopCaption {
    switch (stop.kind) {
      case 'start':
        return room.startedAt === null ? { is: 'none' } : { is: 'time', at: room.startedAt }
      case 'agent':
        return agentCaption(index)
      case 'draft':
        return nothingToWrite ? { is: 'not_needed' } : { is: 'none' }
      case 'gate':
        return gateCaption()
      case 'write':
        return writeCaption(stop, index)
      case 'done':
        return { is: 'none' }
    }
  }

  function castOf(stop: LineStop, index: number): Figure[] {
    const figures: Figure[] = []
    if (stop.kind === 'start' && room.starter) {
      const { starter } = room
      figures.push({ key: `person:${starter.id}`, is: 'person', id: starter.id, name: starter.display, acting: starter.id === actingId, verdict: null })
    }
    for (const seat of room.agents) {
      if (place(seat.at) !== index) continue
      figures.push({ key: `agent:${seat.id}`, is: 'agent', id: seat.id, name: seat.display, acting: seat.id === actingId, status: seat.status })
    }
    if (stop.kind === 'gate') for (const step of steps) figures.push(stepFigure(step, actingId))
    return figures
  }

  function formOf(stop: LineStop): ParcelForm {
    if (breakAt !== null) return { is: 'stopped' }
    if (decliner !== null) return { is: 'declined' }
    const written = stop.kind === 'write' ? references(linesAt(stop.connector)) : stop.kind === 'done' ? references(ticket?.lines ?? []) : []
    if (written.length > 0) return { is: 'written', references: itemsOf(written, 1) }
    if (ticket) return { is: 'draft', noun: nounOf(ticket.lines.map((candidate) => candidate.operation)), count: ticket.lines.length }
    if (room.finding) return { is: 'found', items: itemsOf(room.finding.items, PARCEL_CHIPS) }
    return { is: 'request' }
  }

  function headlineOf(): Headline {
    if (phase.name === 'empty') return { is: 'not_started' }
    if (phase.name === 'pending') return { is: 'starting' }
    if (breakAt !== null) return { is: 'stopped' }
    if (decliner !== null) return { is: 'declined', by: decliner.display }
    const writtenLines = (ticket?.lines ?? []).flatMap((candidate) =>
      candidate.reference === null ? [] : [{ reference: candidate.reference, connector: candidate.connector }],
    )
    switch (phase.name) {
      case 'working': {
        let latest: AgentSeat | undefined
        for (const seat of room.agents) if (seat.step && seat.step.seq > (latest?.step?.seq ?? 0)) latest = seat
        if (latest?.step?.state !== 'running' && room.finding) return { is: 'found', step: room.finding.step, count: room.finding.items.length }
        const working = latest ?? room.agents.findLast((seat) => seat.role === 'specialist')
        return { is: 'working', agent: working?.id ?? null }
      }
      case 'proposed':
        return { is: 'drafting', noun: nounOf((ticket?.lines ?? []).map((candidate) => candidate.operation)), count: ticket?.lines.length ?? 0 }
      case 'awaiting_approval':
        return { is: 'waiting' }
      case 'acting':
        return writtenLines.length > 0 ? { is: 'written', lines: writtenLines } : { is: 'approved', by: approvers(steps) }
      case 'succeeded':
        return phase.outcome === 'nothing_to_write' ? { is: 'nothing_to_write' } : { is: 'written', lines: writtenLines }
      default:
        return { is: 'stopped' }
    }
  }

  function panelOf(gate: Gate | null): PanelSpot | null {
    const open = openStep(room)
    if (gate && open && room.approval) return { is: 'approval', stop: gate.stop, approvalId: room.approval.id, step: open.index }
    if (phase.name === 'failed' && breakAt !== null) return { is: 'trouble', stop: breakAt, retryable: phase.retryable, attempt: room.attempt }
    const written = (ticket?.lines ?? []).flatMap((candidate): WrittenLine[] =>
      candidate.reference === null
        ? []
        : [{ connector: candidate.connector, reference: candidate.reference, title: splitActionLine(candidate.line).title, at: candidate.writtenAt }],
    )
    const lastLine = written.at(-1)
    if (!lastLine) return null
    return { is: 'written', stop: place({ at: 'write', connector: lastLine.connector }), lines: written, approvedBy: approvers(steps) }
  }

  const gateIndex = line.findIndex((stop) => stop.kind === 'gate')
  const gate: Gate | null =
    gateIndex < 0
      ? null
      : {
          stop: gateIndex,
          state: gateStateOf(steps, nothingToWrite),
          approvalId: room.approval?.id ?? null,
          link: room.approval?.link ?? null,
          openStep: openStep(room)?.index ?? null,
          teamsFailed: room.approval?.teams.is === 'failed',
        }

  const speaker = room.speech ? room.agents.find((seat) => seat.id === room.speech?.speaker) : undefined
  const parcelStop = current === null ? undefined : line[current]

  return {
    stops: line.map((stop, index) => ({ key: stop.key, kind: stop.kind, name: stop.name, state: stateOf(stop, index), caption: captionOf(stop, index), cast: castOf(stop, index) })),
    parcel: current === null || !parcelStop ? null : { at: current, before: parcelStop.kind === 'gate', form: formOf(parcelStop) },
    gate,
    breakAt,
    cut,
    speech: room.speech
      ? { seq: room.speech.seq, stop: speaker ? place(speaker.at) : (current ?? 0), speaker: room.speech.speaker, name: speaker?.display ?? room.speech.speaker, text: room.speech.text }
      : null,
    panel: panelOf(gate),
    headline: headlineOf(),
    subline: room.latest?.summary ?? '',
    attempt: room.attempt,
  }
}
