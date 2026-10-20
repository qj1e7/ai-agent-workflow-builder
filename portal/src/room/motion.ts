import type { Point } from '../run'

export const EASE_MOVE = 'cubic-bezier(0.65, 0, 0.35, 1)'
export const EASE_OVERSHOOT = 'cubic-bezier(0.3, 1.4, 0.5, 1)'

/** A piece landing in place: fade and scale from 0.92. */
export const APPEAR_MS = 220
export const APPEAR: Keyframe[] = [
  { transform: 'scale(0.92)', opacity: 0 },
  { transform: 'scale(1)', opacity: 1 },
]

export const FADE_OUT: Keyframe[] = [{ opacity: 1 }, { opacity: 0 }]

/** The share of a beat a token spends travelling before what it brought appears. */
export const TRAVEL_SHARE = 0.7

export interface TravelOptions {
  readonly fadeIn?: boolean
  readonly fadeOut?: boolean
}

/**
 * Keyframes that walk an element along a polyline that ends where the element rests, using transform only.
 * fadeIn lifts the first fifth of the way; fadeOut drops the last fifth, so a token vanishes as it lands.
 */
export function travelAlong(path: readonly Point[], extra: TravelOptions = {}): Keyframe[] {
  const end = path[path.length - 1]
  if (!end || path.length < 2) return []
  const lengths: number[] = []
  let total = 0
  for (let i = 1; i < path.length; i += 1) {
    const a = path[i - 1] as Point
    const b = path[i] as Point
    const length = Math.hypot(b.x - a.x, b.y - a.y)
    lengths.push(length)
    total += length
  }
  if (total === 0) return []
  const at = (p: Point) => `translate(${p.x - end.x}px, ${p.y - end.y}px)`
  const frames: Keyframe[] = []
  let walked = 0
  path.forEach((p, i) => {
    if (i > 0) walked += lengths[i - 1] as number
    frames.push({ offset: walked / total, transform: at(p), opacity: 1 })
  })
  const lift = 0.12
  if (extra.fadeIn) {
    const first = frames[0] as Keyframe
    first.opacity = 0
    frames.splice(1, 0, { offset: Math.min(lift, (frames[1]?.offset as number) || lift), transform: at(pointAlong(path, lengths, total, lift)), opacity: 1 })
  }
  if (extra.fadeOut) {
    const last = frames[frames.length - 1] as Keyframe
    last.opacity = 0
    frames.splice(frames.length - 1, 0, { offset: Math.max(1 - lift, (frames[frames.length - 2]?.offset as number) || 1 - lift), transform: at(pointAlong(path, lengths, total, 1 - lift)), opacity: 1 })
  }
  return frames.sort((a, b) => (a.offset as number) - (b.offset as number))
}

function pointAlong(path: readonly Point[], lengths: readonly number[], total: number, t: number): Point {
  let target = t * total
  for (let i = 1; i < path.length; i += 1) {
    const length = lengths[i - 1] as number
    if (target <= length || i === path.length - 1) {
      const a = path[i - 1] as Point
      const b = path[i] as Point
      const f = length === 0 ? 0 : target / length
      return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }
    }
    target -= length
  }
  return path[path.length - 1] as Point
}

export const STAMP: Keyframe[] = [
  { transform: 'rotate(-6deg) scale(1.7)', opacity: 0 },
  { transform: 'rotate(-6deg) scale(1)', opacity: 1 },
]

export const POP: Keyframe[] = [
  { transform: 'scale(1.8)', opacity: 0 },
  { transform: 'scale(1)', opacity: 1 },
]
