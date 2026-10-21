import type { ActivityEvent } from '../api/types'
import { beatMsOf, isStory, LONG_GAP_MS } from '../run'

export const WAIT_HEAD_MS = 4000
export const SQUEEZE = 40
export const SHORT_GAP_CAP_MS = 1000

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

function stamp(event: ActivityEvent, ts: number): ActivityEvent {
  return { ...event, ts: new Date(ts).toISOString() }
}

function recordedOffsets(events: readonly ActivityEvent[]): number[] {
  const first = events[0] ? Date.parse(events[0].ts) : 0
  return events.map((event) => Date.parse(event.ts) - first)
}

/**
 * The demo's pace: short gaps play at their recorded length capped at a second, a story event never
 * lands before the previous story event's beat has played, and a long wait plays its head at real speed
 * and the rest squeezed. Outside a wait the event's recorded time moves with the wall, so the run clock
 * stays 1:1 and the room never has to catch up.
 */
export function replay(events: readonly ActivityEvent[], start: Anchor): Entry[] {
  const offsets = recordedOffsets(events)
  let wall = start.wall
  let ts = start.recorded
  let lastStory: { readonly wall: number; readonly event: ActivityEvent } | null = null
  return events.map((event, index) => {
    const gap = index > 0 ? (offsets[index] ?? 0) - (offsets[index - 1] ?? 0) : 0
    const wait = gap > LONG_GAP_MS
    if (wait) {
      wall += Math.round(WAIT_HEAD_MS + (gap - WAIT_HEAD_MS) / SQUEEZE)
      ts += gap
    } else {
      let advance = Math.min(gap, SHORT_GAP_CAP_MS)
      if (lastStory && isStory(event)) advance = Math.max(advance, lastStory.wall + beatMsOf(lastStory.event) - wall)
      wall += advance
      ts += advance
    }
    if (isStory(event)) lastStory = { wall, event }
    return { at: wall, ts, squeezed: wait, event: stamp(event, ts) }
  })
}

export function finished(events: readonly ActivityEvent[], recordedStart: number): Entry[] {
  const offsets = recordedOffsets(events)
  return events.map((event, index) => {
    const ts = recordedStart + (offsets[index] ?? 0)
    return { at: ts, ts, squeezed: false, event: stamp(event, ts) }
  })
}

interface Place {
  readonly previous: Entry
  readonly next: Entry | undefined
  readonly elapsed: number
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
    const { previous, next, elapsed } = this.place(wall)
    if (!next?.squeezed || elapsed <= WAIT_HEAD_MS) return previous.ts + elapsed
    return Math.min(next.ts, previous.ts + WAIT_HEAD_MS + (elapsed - WAIT_HEAD_MS) * SQUEEZE)
  }

  rateAt(wall: number): number {
    const first = this.entries[0]
    if (!first || wall < first.at) return 1
    const { next, elapsed } = this.place(wall)
    return next?.squeezed && elapsed > WAIT_HEAD_MS ? SQUEEZE : 1
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

  private place(wall: number): Place {
    const index = this.entries.findLastIndex((entry) => entry.at <= wall)
    const previous = this.entries[index] as Entry
    return { previous, next: this.entries[index + 1], elapsed: wall - previous.at }
  }

  private notify(): void {
    for (const listener of this.listeners) listener()
  }
}
