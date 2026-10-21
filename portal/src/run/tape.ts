import type { Actor } from '../api/types'
import type { RunEvent } from '../stream/parse'
import type { RunTime, Seq, WallTime } from './brand'
import { ruleOf } from './kinds'
import { applyEvent, EMPTY_ROOM, type AgentRegistry, type RoomState } from './room'

export type Origin = 'backlog' | 'live'

export interface MinutesEntry {
  readonly seq: Seq
  readonly at: RunTime
  readonly actor: Actor
  readonly summary: string
  readonly tier: 'story' | 'technical'
  /** Raw kind, shown only under technical details. */
  readonly kind: string
  readonly attempt: number
  /** agent_message text, so the Minutes can quote it. */
  readonly quote: string | null
}

export interface Arrival {
  readonly at: WallTime
  readonly origin: Origin
}

export interface TapeReader {
  readonly length: number
  /** 1..length */
  event(seq: number): RunEvent
  /** 0..length. frame(0) is EMPTY_ROOM. O(1): every frame is stored as it is folded. */
  frame(cursor: number): RoomState
  arrival(seq: number): Arrival
  /** The latest timestamp on the tape. Event times need not grow with seq when two clocks stamp them. */
  latestAt(): RunTime | null
  /** Append-only; a slice of the first n is a stable snapshot. */
  minutes(): readonly MinutesEntry[]
}

export interface Tape extends TapeReader {
  /**
   * Idempotent by seq: an event whose seq is not length + 1 is ignored. So a duplicate, a double-invoked
   * StrictMode effect or a feed restart from an old resume point cannot corrupt the log.
   * Folds each accepted event once and stores its frame and minutes entry. Returns the new length.
   */
  append(events: readonly RunEvent[], origin: Origin, at: WallTime): number
}

export function createTape(registry: AgentRegistry): Tape {
  const events: RunEvent[] = []
  const frames: RoomState[] = [EMPTY_ROOM]
  const arrivals: Arrival[] = []
  const minutes: MinutesEntry[] = []
  let latest: RunTime | null = null

  function at(seq: number): number {
    if (seq < 1 || seq > events.length) throw new RangeError(`seq ${seq} is not on the tape (1..${events.length})`)
    return seq - 1
  }

  return {
    get length() {
      return events.length
    },
    event: (seq) => events[at(seq)] as RunEvent,
    frame: (cursor) => {
      const frame = frames[cursor]
      if (!frame) throw new RangeError(`frame ${cursor} is not on the tape (0..${events.length})`)
      return frame
    },
    arrival: (seq) => arrivals[at(seq)] as Arrival,
    latestAt: () => latest,
    minutes: () => minutes,
    append(incoming, origin, wall) {
      for (const event of incoming) {
        if (event.seq !== events.length + 1) continue
        const previous = frames[frames.length - 1] as RoomState
        const room = applyEvent(previous, event, registry)
        const tier = ruleOf(event).tier
        events.push(event)
        latest = latest === null || event.at > latest ? event.at : latest
        frames.push(room)
        arrivals.push({ at: wall, origin })
        minutes.push({
          seq: event.seq,
          at: event.at,
          actor: event.actor,
          summary: event.summary,
          tier,
          kind: event.kind === 'opaque' ? event.declaredKind : event.kind,
          attempt: room.attempt,
          quote: event.kind === 'agent_message' ? event.data.text : null,
        })
      }
      return events.length
    },
  }
}
