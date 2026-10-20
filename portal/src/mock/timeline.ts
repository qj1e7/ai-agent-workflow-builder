import type { ActivityEvent } from '../api/types'

export const REAL_TIME_GAP_MS = 4000
/**
 * The demo's recorded wait between the approval request and Bob's decision is 372.8 s; at 40 it replays in
 * 4 + 368.8 / 40 = 13.2 s, so the approval pause stays on screen for about six seconds after the room's
 * reading-held speech has caught up to it.
 */
const SQUEEZE_FACTOR = 40

export interface Entry {
  readonly at: number
  readonly ts: number
  readonly squeezed: boolean
  readonly event: ActivityEvent
}

export interface Anchor {
  readonly wall: number
  readonly recorded: number
}

export function squeezeGap(gapMs: number): number {
  return gapMs <= REAL_TIME_GAP_MS ? gapMs : REAL_TIME_GAP_MS + (gapMs - REAL_TIME_GAP_MS) / SQUEEZE_FACTOR
}

function stamp(event: ActivityEvent, ts: number): ActivityEvent {
  return { ...event, ts: new Date(ts).toISOString() }
}

function recordedOffsets(events: readonly ActivityEvent[]): number[] {
  const first = events[0] ? Date.parse(events[0].ts) : 0
  return events.map((event) => Date.parse(event.ts) - first)
}

export function replay(events: readonly ActivityEvent[], start: Anchor): Entry[] {
  const offsets = recordedOffsets(events)
  let at = start.wall
  return events.map((event, index) => {
    const offset = offsets[index] ?? 0
    const gap = index > 0 ? offset - (offsets[index - 1] ?? 0) : 0
    at += squeezeGap(gap)
    const ts = start.recorded + offset
    return { at, ts, squeezed: gap > REAL_TIME_GAP_MS, event: stamp(event, ts) }
  })
}

export function finished(events: readonly ActivityEvent[], recordedStart: number): Entry[] {
  const offsets = recordedOffsets(events)
  return events.map((event, index) => {
    const ts = recordedStart + (offsets[index] ?? 0)
    return { at: ts, ts, squeezed: false, event: stamp(event, ts) }
  })
}

/**
 * A run's events, each with the wall time it appears and the recorded time it claims.
 * The replay clock is the map between the two.
 */
export class Timeline {
  private entries: Entry[]
  private readonly listeners = new Set<() => void>()

  constructor(entries: readonly Entry[] = []) {
    this.entries = [...entries]
  }

  emitted(wall: number): ActivityEvent[] {
    return this.entries.filter((entry) => entry.at <= wall).map((entry) => entry.event)
  }

  nextDue(wall: number): number | undefined {
    return this.entries.find((entry) => entry.at > wall)?.at
  }

  get lastSeq(): number {
    return this.entries.at(-1)?.event.seq ?? 0
  }

  get lastAt(): number {
    return this.entries.at(-1)?.at ?? 0
  }

  recordedAt(wall: number): number {
    const first = this.entries[0]
    if (!first) return wall
    if (wall < first.at) return first.ts - (first.at - wall)
    const index = this.entries.findLastIndex((entry) => entry.at <= wall)
    const previous = this.entries[index] as Entry
    const next = this.entries[index + 1]
    const elapsed = wall - previous.at
    if (!next) return previous.ts + elapsed
    if (!next.squeezed || elapsed <= REAL_TIME_GAP_MS) return previous.ts + elapsed
    return Math.min(next.ts, previous.ts + REAL_TIME_GAP_MS + (elapsed - REAL_TIME_GAP_MS) * SQUEEZE_FACTOR)
  }

  append(entries: readonly Entry[]): void {
    this.entries.push(...entries)
    this.notify()
  }

  discardPendingDecision(wall: number): void {
    const index = this.entries.findIndex((entry) => entry.at > wall && entry.event.kind === 'approval_decided')
    if (index >= 0) this.entries.length = index
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private notify(): void {
    for (const listener of this.listeners) listener()
  }
}
