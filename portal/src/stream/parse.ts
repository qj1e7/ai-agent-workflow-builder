import type { ActivityEvent, Actor } from '../api/types'
import type { RunId, RunTime, Seq } from '../run/brand'

export type EventKind = ActivityEvent['kind']
type WireOf<K extends EventKind> = Extract<ActivityEvent, { kind: K }>
export type DataOf<K extends EventKind> = WireOf<K>['data']

export interface Envelope {
  readonly seq: Seq
  readonly at: RunTime
  readonly actor: Actor
  readonly summary: string
}

/** Derived from the generated union, never written by hand. A new kind in openapi.json appears here on `npm run generate`. */
export type KnownEvent = {
  [K in EventKind]: Envelope & { readonly kind: K; readonly data: DataOf<K> }
}[EventKind]

/**
 * An event this Portal cannot read: an unknown kind from a newer backend, or a known kind whose data
 * lacks a key the room needs. It keeps its seq so the log stays gapless, and it shows only under
 * technical details.
 */
export interface OpaqueEvent extends Envelope {
  readonly kind: 'opaque'
  readonly declaredKind: string
}

export type RunEvent = KnownEvent | OpaqueEvent
export type EventOf<K extends RunEvent['kind']> = Extract<RunEvent, { kind: K }>

export type Parsed =
  | { readonly ok: true; readonly event: RunEvent }
  /** The envelope itself is broken (no seq, wrong run, bad ts). The event cannot be placed, so the feed reconnects. */
  | { readonly ok: false; readonly problem: string }

type RequiredKeys = { readonly [K in EventKind]: readonly (keyof DataOf<K>)[] }

/**
 * The data keys the room reads for each kind. Presence is all that is checked: an unexpected enum
 * value must still show (labels fall back to the raw value), and a newer backend may add keys.
 * `satisfies` makes a kind added to the contract a type error until it has a row.
 */
const REQUIRED_KEYS = {
  run_created: ['started_by', 'use_case_id'],
  leg_dispatched: ['leg', 'attempt'],
  step_started: ['step'],
  step_finished: ['step', 'outcome'],
  step_retried: ['step'],
  agent_joined: ['agent'],
  agent_step_started: ['step'],
  agent_step_finished: ['step'],
  agent_failed: ['message', 'retryable'],
  agent_message: ['speaker', 'addressee', 'text'],
  write_action_proposed: ['proposal_id', 'digest', 'actions'],
  approval_requested: ['approval_id', 'steps', 'link'],
  approval_announced: ['approval_id', 'channel'],
  approval_announce_failed: ['approval_id', 'channel', 'message'],
  approval_decided: ['approval_id', 'step', 'verdict', 'by'],
  write_action_denied: ['reason', 'detail'],
  write_action_done: ['connector', 'operation', 'external_reference'],
  run_succeeded: ['outcome'],
  run_rejected: ['by', 'step'],
  run_failed: ['stage', 'reason', 'retryable', 'message'],
  run_retried: ['leg', 'attempt'],
} as const satisfies RequiredKeys

const ACTOR_KINDS: ReadonlySet<string> = new Set(['user', 'platform', 'workflow', 'agent', 'safety_checker'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readEnvelope(raw: Record<string, unknown>, runId: RunId): Envelope | string {
  const { seq, run_id: run, ts, actor, summary } = raw
  if (typeof seq !== 'number' || !Number.isInteger(seq) || seq < 1) return 'seq must be a positive integer'
  if (run !== runId) return `run_id ${String(run)} is not ${runId}`
  const at = typeof ts === 'string' ? Date.parse(ts) : Number.NaN
  if (Number.isNaN(at)) return 'ts does not parse'
  if (!isRecord(actor) || typeof actor['id'] !== 'string' || typeof actor['display'] !== 'string') {
    return 'actor needs id and display'
  }
  if (typeof actor['kind'] !== 'string' || !ACTOR_KINDS.has(actor['kind'])) return 'actor needs a kind'
  if (typeof summary !== 'string') return 'summary must be a string'
  return {
    seq: seq as Seq,
    at: at as RunTime,
    actor: { kind: actor['kind'] as Actor['kind'], id: actor['id'], display: actor['display'] },
    summary,
  }
}

function hasRequiredKeys(kind: EventKind, data: Record<string, unknown>): boolean {
  const keys: readonly string[] = REQUIRED_KEYS[kind]
  return keys.every((key) => data[key] !== undefined && data[key] !== null)
}

function isKnownKind(kind: string): kind is EventKind {
  return Object.hasOwn(REQUIRED_KEYS, kind)
}

/**
 * The only place in the engine that sees `unknown`. The envelope is checked strictly, because an
 * event without a place in the log cannot be shown at all. The data is checked leniently.
 */
export function parseEvent(raw: unknown, runId: RunId): Parsed {
  if (!isRecord(raw)) return { ok: false, problem: 'event is not an object' }
  const envelope = readEnvelope(raw, runId)
  if (typeof envelope === 'string') return { ok: false, problem: envelope }
  const kind = raw['kind']
  const declaredKind = typeof kind === 'string' ? kind : String(kind)
  const data = raw['data']
  if (typeof kind !== 'string' || !isKnownKind(kind) || !isRecord(data) || !hasRequiredKeys(kind, data)) {
    return { ok: true, event: { ...envelope, kind: 'opaque', declaredKind } }
  }
  // The single cast in the engine: the required keys are present, and every other field is read as-is.
  return { ok: true, event: { ...envelope, kind, data } as KnownEvent }
}

export type ParsedPage =
  | { readonly ok: true; readonly events: readonly RunEvent[] }
  | { readonly ok: false; readonly problem: string }

/** `GET /runs/{id}/events?after=n` answer. One broken envelope fails the page. */
export function parsePage(raw: unknown, runId: RunId): ParsedPage {
  if (!isRecord(raw) || !Array.isArray(raw['events'])) return { ok: false, problem: 'page has no events list' }
  const events: RunEvent[] = []
  for (const item of raw['events'] as unknown[]) {
    const parsed = parseEvent(item, runId)
    if (!parsed.ok) return parsed
    events.push(parsed.event)
  }
  return { ok: true, events }
}

export const TERMINAL_KINDS: ReadonlySet<RunEvent['kind']> = new Set(['run_succeeded', 'run_rejected', 'run_failed'])
