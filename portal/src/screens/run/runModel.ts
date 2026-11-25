import type { ApprovalStepStatus, ApproverRef, BlockKind, FailureReason, FailureStage, RunOutcome, Trigger, Verdict } from '../../api/types'
import { runId as asRunId, type RunTime } from '../../stream/brand'
import { parseEvent, type DataOf, type EventOf, type RunEvent } from '../../stream/parse'
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

/** Why a fix was handed back, as the hand-back event's code says it. */
export type FixHandBack = DataOf<'fix_handed_back'>['why']

/** A sub-agent a fix brought in, and the event that brought it, so one that arrives live can rise in. */
export interface BroughtIn {
  readonly agent: AgentRef
  readonly seq: number
}

/**
 * A fix on the stopped run (ADR 0055): the sub-agents it brought in, in order, how an event ended it, or null, and when it runs
 * out of time. Read where it stands with fixEnd, which counts the deadline.
 */
export interface FixState {
  readonly id: string
  readonly agents: readonly BroughtIn[]
  readonly ended: 'proposed' | 'handed_back' | null
  readonly endsBy: RunTime
  /** Each round's sentence, as the platform wrote it, for the hand-back card. */
  readonly rounds: readonly string[]
  /** The hand-back's reason code, once an event gave it. */
  readonly why: FixHandBack | null
}

/** How a fix ended by now: as an event said, or handed back once its deadline passed with no event, as the platform counts it. */
export function fixEnd(fix: FixState, now: number): 'proposed' | 'handed_back' | null {
  if (fix.ended !== null) return fix.ended
  return now >= fix.endsBy ? 'handed_back' : null
}

/** One entry in the run's log, placed and timed by the event that made it. */
export type ChatItem = { readonly seq: number; readonly at: RunTime } & (
  | { readonly kind: 'started'; readonly by: string; readonly trigger: Trigger }
  | { readonly kind: 'joined'; readonly agents: readonly AgentRef[] }
  | { readonly kind: 'said'; readonly speaker: AgentRef; readonly text: string; readonly bad: boolean }
  /** A request for a yes. Once the platform says it was posted to Teams, who may decide each step, in step order. */
  | { readonly kind: 'asked'; readonly channel: string | null; readonly posted: boolean | null; readonly sentTo: readonly (readonly ApproverRef[])[] }
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
  /**
   * An agent read a release source. The newest release it found, or null when there was none. A read that failed carries why
   * (an empty string when the platform gave no reason), and is never the same as a read that found nothing. `source` is where it
   * read, such as npm, Maven Central or GitHub, and `software` which software or repository.
   */
  | { readonly kind: 'checked'; readonly newest: string | null; readonly problem: string | null; readonly source: string | null; readonly software: string | null }
  /** The agents drafted these writes for approval. */
  | { readonly kind: 'drafted'; readonly count: number; readonly connector: string | null; readonly operation: string | null; readonly allTickets: boolean }
  /** What a Tell block did, in the platform's own words: sent, not confirmed, what a test run would have sent, or nothing to report. */
  | { readonly kind: 'told'; readonly line: string; readonly bad: boolean }
  /** A step of a fix, in the sentence the platform wrote from its fields. The speaker is the agent, or nobody for who asked. */
  | { readonly kind: 'fix'; readonly speaker: AgentRef | null; readonly text: string; readonly tone: 'plain' | 'bad' | 'wait' }
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
  /** What each proposed action does, such as create_ticket, so the run can say what it writes before the first write lands. */
  readonly operations: readonly string[]
  readonly connector: string | null
  readonly written: readonly Written[]
  readonly approvedBy: readonly string[]
  /** Why the Approver declined, from the decline event, when they gave a reason. */
  readonly declineReason: string | null
  readonly retriedBy: readonly string[]
  /** What the agents said they found, from the step that closed their work. Kept after the approval stops carrying it. */
  readonly found: string
  /** The newest release the run read, and the day it came out when the read says. The page's found line is built from this, never from the agents' words. */
  readonly release: Release | null
  /** The reports to support about this stop, one for each request. A retry starts the list again. */
  readonly reports: readonly { readonly requestId: string; readonly by: string }[]
  /** The fix on this stop, once someone asked for one. A retry forgets it. It never moves the run. */
  readonly fix: FixState | null
  readonly people: Readonly<Record<string, string>>
  readonly chat: readonly ChatItem[]
}

/** The newest release a run read: its version, and the day it came out when the event carries one. */
export interface Release {
  readonly version: string
  readonly at: string | null
}

/** What a read of releases found, from the two shapes agents report it in: a card's tags, or the software check's newest. */
interface ReadOf {
  readonly read: boolean
  readonly release: Release | null
  readonly problem: string | null
  readonly source: string | null
  readonly software: string | null
}

const NOT_A_READ: ReadOf = { read: false, release: null, problem: null, source: null, software: null }

function readOf(data: { readonly step: string; readonly result: Readonly<Record<string, unknown>> }): ReadOf {
  const { step, result } = data
  if (step !== 'github_read_releases' && step !== 'read_source') return NOT_A_READ
  const text = (key: string) => (typeof result[key] === 'string' && result[key] !== '' ? result[key] : null)
  const source = text('source') ?? (step === 'github_read_releases' ? 'GitHub' : null)
  const software = text('software') ?? text('repo')
  const problem = typeof result['problem'] === 'string' ? result['problem'] : result['state'] === 'cant_check' ? '' : null
  const tags = Array.isArray(result['tags']) ? result['tags'] : []
  const newest = typeof result['newest'] === 'string' ? result['newest'] : tags.find((tag): tag is string => typeof tag === 'string')
  if (problem !== null || newest === undefined || newest === '') return { read: true, release: null, problem, source, software }
  const day = result['newest_published_at']
  return { read: true, release: { version: newest, at: typeof day === 'string' && day !== '' ? day : null }, problem: null, source, software }
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
  operations: [],
  connector: null,
  written: [],
  approvedBy: [],
  declineReason: null,
  retriedBy: [],
  found: '',
  release: null,
  reports: [],
  fix: null,
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

/** Where a stop sits. One while the run was still starting, such as n8n not taking the start, sits on the start, not after it. */
function failedSpot(model: RunModel, stage: FailureStage): Spot {
  if (model.failedAt) return model.failedAt
  switch (stage) {
    case 'pending':
      return { at: 'started' }
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
    fix: null,
  }
  const next: RunModel =
    event.data.leg === 'work'
      ? { ...base, phase: { state: 'pending' }, agents: [], approvalId: null, steps: [], proposed: 0, operations: [], written: [], found: '' }
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

/**
 * The sub-agents a fix brings in, as Orbs. The AI troubleshooter is the fix's own face, and the simulation and the platform's
 * check are code, so they are not brought in.
 */
const SUB_AGENTS: Readonly<Partial<Record<DataOf<'fix_handoff'>['to'], AgentRef>>> = {
  fix_drafter: { id: 'fix_drafter', display: 'Fix drafter' },
  scenario_writer: { id: 'scenario_writer', display: 'Scenario writer' },
}

/** What the platform found that the fix can't use. */
const REFUSED: ReadonlySet<DataOf<'fix_handoff'>['found']> = new Set(['not_in_version', 'not_where_it_stopped', 'too_wide', 'widened', 'not_in_catalogue', 'refused', 'failed', 'no_answer'])

type FixEvent = EventOf<'fix_started' | 'fix_handoff' | 'fix_round' | 'fix_proposed' | 'fix_handed_back' | 'fix_decided' | 'fix_tried'>

function fixOf(fix: FixState | null, event: FixEvent): FixState | null {
  if (event.kind === 'fix_started') return { id: event.data.fix_id, agents: [], ended: null, endsBy: Date.parse(event.data.ends_by) as RunTime, rounds: [], why: null }
  if (fix === null || fix.id !== event.data.fix_id) return fix
  switch (event.kind) {
    case 'fix_handoff': {
      const agent = SUB_AGENTS[event.data.to]
      if (agent === undefined || fix.agents.some((brought) => brought.agent.id === agent.id)) return fix
      return { ...fix, agents: [...fix.agents, { agent, seq: event.seq }] }
    }
    case 'fix_proposed':
      return { ...fix, ended: 'proposed' }
    case 'fix_handed_back':
      return { ...fix, ended: 'handed_back', why: event.data.why }
    case 'fix_round':
      return { ...fix, rounds: [...fix.rounds, event.summary] }
    case 'fix_decided':
    case 'fix_tried':
      return fix
  }
}

function fixTone(event: FixEvent): 'plain' | 'bad' | 'wait' {
  switch (event.kind) {
    case 'fix_handoff':
      return REFUSED.has(event.data.found) ? 'bad' : 'plain'
    case 'fix_round':
      return event.data.round > 1 && !event.data.progress ? 'bad' : 'plain'
    case 'fix_proposed':
      return 'wait'
    case 'fix_handed_back':
      return 'bad'
    case 'fix_decided':
      return event.data.verdict === 'declined' ? 'bad' : 'plain'
    case 'fix_tried':
      return event.data.result === 'test_failed' || event.data.result === 'not_put_live' ? 'bad' : 'plain'
    case 'fix_started':
      return 'plain'
  }
}

/** A step of a fix. It adds to the log and the fix, and never moves the run: it stays stopped where it stopped. */
function fixed(model: RunModel, event: FixEvent): RunModel {
  const speaker = event.kind === 'fix_started' || event.kind === 'fix_decided' || event.kind === 'fix_tried' || event.actor.kind !== 'agent' ? null : actorRef(event)
  return say({ ...model, fix: fixOf(model.fix, event) }, { kind: 'fix', seq: event.seq, at: event.at, speaker, text: event.summary, tone: fixTone(event) })
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
      return touch(model, actorRef(event), event)
    case 'agent_step_finished': {
      const touched = touch(model, actorRef(event), event)
      const { read, release, problem, source, software } = readOf(event.data)
      if (!read) return touched
      return say({ ...touched, release: release ?? touched.release }, { kind: 'checked', seq: event.seq, at: event.at, newest: release?.version ?? null, problem, source, software })
    }
    case 'agent_failed': {
      const touched = touch(model, actorRef(event), event)
      const failedAt = placeAgent(touched, actorRef(event)).spot
      return say({ ...touched, failedAt }, { kind: 'said', seq: event.seq, at: event.at, speaker: actorRef(event), text: event.data.message, bad: true })
    }
    case 'write_action_proposed': {
      const phase = model.phase.state === 'pending' || model.phase.state === 'working' ? { state: 'proposed' as const } : model.phase
      const { actions } = event.data
      const first = actions[0]
      const moved = { ...model, phase, proposed: actions.length, operations: actions.map((action) => action.operation), connector: first?.connector ?? model.connector }
      const allTickets = actions.length > 0 && actions.every((action) => action.connector === 'jira' && action.operation === 'create_ticket')
      return say(moved, { kind: 'drafted', seq: event.seq, at: event.at, count: actions.length, connector: first?.connector ?? null, operation: first?.operation ?? null, allTickets })
    }
    case 'approval_requested': {
      const steps = event.data.steps.map((s) => ({ index: s.index, label: s.label, status: s.status, by: s.decided_by ?? null }))
      const next = advanceTo({ ...model, approvalId: event.data.approval_id, steps, phase: { state: 'awaiting_approval' } }, { at: 'gate' }, event)
      return say(next, { kind: 'asked', seq: event.seq, at: event.at, channel: null, posted: null, sentTo: [] })
    }
    case 'approval_announced':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, at: item?.at ?? event.at, channel: event.data.channel, posted: true, sentTo: event.data.sent_to ?? [] }))
    case 'approval_announce_failed':
      return amendLast(model, 'asked', (item) => ({ kind: 'asked', seq: item?.seq ?? event.seq, at: item?.at ?? event.at, channel: event.data.channel, posted: false, sentTo: [] }))
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
    case 'step_finished': {
      const { step, outcome, detail } = event.data
      if (step !== 'run_agents' || !FOUND_OUTCOMES.has(outcome) || !detail) return model
      // The agents' report is kept for the troubleshooter's rows, and is not a log item: it only repeats what they said.
      return { ...model, found: detail }
    }
    case 'support_reported':
      return reported(model, event)
    case 'told':
      return say(model, { kind: 'told', seq: event.seq, at: event.at, line: event.data.line, bad: event.data.status === 'not_confirmed' })
    case 'fix_started':
    case 'fix_handoff':
    case 'fix_round':
    case 'fix_proposed':
    case 'fix_handed_back':
    case 'fix_decided':
    case 'fix_tried':
      return fixed(model, event)
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
  /** The waiting gate, once its request is in Teams: who may decide the open step, by name. */
  | { readonly kind: 'sent'; readonly to: readonly string[] }
  /** The waiting gate, when its request could not be posted to Teams. */
  | { readonly kind: 'unsent' }

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

/** The step a stop is drawn at. A stop at the start stays on the start step. */
const stopStationOf = (stations: readonly Skeleton[], spot: Spot | null): number => (spot?.at === 'started' ? 0 : stationOf(stations, spot))

function stateOf(model: RunModel, station: Skeleton, index: number, current: number, failed: number): StationState {
  const { phase } = model
  const at = station.spot.at
  const unfilled = at === 'agent' && station.agent === null
  if (at === 'started') return phase.state === 'failed' && index === failed ? 'err' : 'done'
  switch (phase.state) {
    case 'failed':
      if (index === failed) return 'err'
      return index < failed ? (unfilled ? 'skip' : 'done') : 'todo'
    case 'succeeded':
      if (phase.outcome !== 'written' && (at === 'gate' || at === 'write')) return 'skip'
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

/**
 * What the waiting gate says of its request: sent, and to whom, or not sent. Nothing until the platform says either. Who it went
 * to was read when the request was posted, so whoever said yes to an earlier step since is left out by id, as the platform's view
 * of the step leaves them out.
 */
function sentUnder(model: RunModel): Under | null {
  const asked = model.chat.findLast((item) => item.kind === 'asked')
  if (asked?.kind !== 'asked' || asked.posted === null) return null
  if (!asked.posted) return { kind: 'unsent' }
  const open = model.steps.find((step) => step.status === 'open' || step.status === 'waiting')?.index ?? 0
  const before = new Set(model.steps.flatMap((step) => (step.index < open && step.by ? [step.by] : [])))
  return { kind: 'sent', to: (asked.sentTo[open] ?? []).filter((person) => !before.has(person.id)).map((person) => person.display) }
}

function underOf(model: RunModel, stations: readonly Skeleton[], index: number, state: StationState): Under | null {
  const at = stations[index]?.spot.at
  if (at === 'gate' && state === 'wait') return sentUnder(model)
  if (state === 'now') {
    const since = sinceOf(model, stations, index)
    return since === null ? null : { kind: 'timer', since }
  }
  const written = model.written.filter((write) => write.ref !== '')
  if (at === 'write' && state === 'done' && written.length > 0) return { kind: 'tickets', written }
  const tested = model.phase.state === 'succeeded' && model.phase.outcome === 'test_passed'
  if (at === 'write' && state === 'skip' && (model.phase.state === 'rejected' || tested)) return { kind: 'note', text: 'Nothing written' }
  return null
}

/**
 * The run line: the workflow's blocks and nothing else. What started the run, one step per agent, the gate and the write.
 * The plan, when known, names the steps and fixes how many there are, so the line does not grow as agents join.
 */
export function stationsOf(model: RunModel, plan: readonly PlanBlock[] | null, trigger: string): Station[] {
  const stations = skeleton(model, plan, trigger)
  const current = stationOf(stations, model.spot)
  const failed = model.phase.state === 'failed' ? stopStationOf(stations, model.failedAt) : -1
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
