import type { Ms, RunTime } from './brand'
import { LONG_GAP_MS } from './director'
import type { TimelineMark } from './tape'

export interface WaitSegment {
  readonly x: number
  /** Reserved width. Fixed for any finished wait, reserved in full as soon as a live wait starts. */
  readonly w: number
  /** Drawn width: equals w for a finished wait, grows to w over the first thirty seconds of a live one. */
  readonly fill: number
  /** How long it lasted, or has lasted so far when live. The component writes "Waited 6 min 13 s". */
  readonly lasted: Ms
  /** person: someone had to decide (amber hatch). quiet: nothing happened (neutral hatch). */
  readonly tone: 'person' | 'quiet'
  readonly live: boolean
}

export interface ScrubberLayout {
  /** Story events only; technical events still have positions through xOf. */
  readonly ticks: readonly { readonly seq: number; readonly x: number }[]
  readonly waits: readonly WaitSegment[]
  xOf(cursor: number): number
  /** The last event at or before x. Inverse of xOf on tick positions. */
  cursorAt(x: number): number
}

export const SCRUB = { minTickMs: 250, waitMinPx: 64, waitMaxPx: 128, waitShare: 0.16, maxWaitShare: 0.5 } as const

export interface ScrubberInput {
  readonly marks: readonly TimelineMark[]
  readonly width: number
  /** Present only while live at the edge of an unsettled run. */
  readonly edge: { readonly now: RunTime; readonly waitingSince: RunTime | null } | null
}

/**
 * Time-proportional track where every gap over LONG_GAP_MS becomes one fixed-width segment, so the axis
 * neither lies nor stretches. While live and a person is needed, the segment is reserved at the right
 * edge at once (ticks never move while it grows) and its fill grows over the first thirty seconds.
 */
export function layoutScrubber({ marks, width, edge }: ScrubberInput): ScrubberLayout {
  const n = marks.length
  if (n === 0) {
    return { ticks: [], waits: [], xOf: () => 0, cursorAt: () => 0 }
  }
  const gaps: number[] = []
  for (let i = 1; i < n; i += 1) gaps.push((marks[i] as TimelineMark).at - (marks[i - 1] as TimelineMark).at)
  const longs = gaps.map((gap) => gap > LONG_GAP_MS)
  const lastMark = marks[n - 1] as TimelineMark
  const liveWait = edge?.waitingSince ? Math.max(0, edge.now - edge.waitingSince) : null
  const reserveLive = liveWait !== null

  let G = Math.min(SCRUB.waitMaxPx, Math.max(SCRUB.waitMinPx, Math.round(width * SCRUB.waitShare)))
  const fixedCount = longs.filter(Boolean).length + (reserveLive ? 1 : 0)
  if (fixedCount * G > width * SCRUB.maxWaitShare) G = Math.floor((width * SCRUB.maxWaitShare) / fixedCount)
  const fixed = fixedCount * G
  const shortTotal = gaps.reduce((total, gap, i) => (longs[i] ? total : total + Math.max(gap, SCRUB.minTickMs)), 0)
  const k = shortTotal > 0 ? (width - fixed) / shortTotal : 0

  const xs: number[] = [0]
  for (let i = 0; i < gaps.length; i += 1) {
    const step = longs[i] ? G : Math.max(gaps[i] as number, SCRUB.minTickMs) * k
    xs.push((xs[i] as number) + step)
  }
  if (!reserveLive && n > 1) xs[n - 1] = width
  if (!reserveLive && n === 1) xs[0] = 0

  const positions = xs.map((x) => Math.round(x))
  const waits: WaitSegment[] = []
  gaps.forEach((gap, i) => {
    if (!longs[i]) return
    const before = marks[i] as TimelineMark
    const since = before.waitingSince
    waits.push({
      x: positions[i] as number,
      w: G,
      fill: G,
      lasted: since !== null ? (marks[i + 1] as TimelineMark).at - since : gap,
      tone: since !== null ? 'person' : 'quiet',
      live: false,
    })
  })
  if (reserveLive && edge?.waitingSince) {
    const sinceLast = Math.max(0, edge.now - lastMark.at)
    waits.push({
      x: width - G,
      w: G,
      fill: Math.round(G * Math.min(1, sinceLast / LONG_GAP_MS)),
      lasted: liveWait ?? 0,
      tone: 'person',
      live: true,
    })
  }

  const ticks = marks.flatMap((mark, i) => (mark.tier === 'story' ? [{ seq: mark.seq, x: positions[i] as number }] : []))

  return {
    ticks,
    waits,
    xOf(cursor) {
      if (cursor <= 0) return 0
      return positions[Math.min(cursor, n) - 1] as number
    },
    cursorAt(x) {
      let cursor = 1
      for (let i = 0; i < n; i += 1) if ((positions[i] as number) <= x) cursor = i + 1
      return cursor
    },
  }
}
