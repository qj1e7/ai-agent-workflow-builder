import type { Point } from '../run'

export const EASE_MOVE = 'cubic-bezier(0.65, 0, 0.35, 1)'
export const EASE_OVERSHOOT = 'cubic-bezier(0.3, 1.4, 0.5, 1)'

/** Keyframes that walk an element along a polyline that ends where the element rests, using transform only. */
export function travelAlong(path: readonly Point[], extra: { readonly fadeIn?: boolean; readonly tilt?: number } = {}): Keyframe[] {
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
  const frames: Keyframe[] = []
  let walked = 0
  path.forEach((p, i) => {
    if (i > 0) walked += lengths[i - 1] as number
    const offset = walked / total
    const tilt = extra.tilt !== undefined && offset < 1 ? ` rotate(${extra.tilt}deg)` : ''
    frames.push({
      offset,
      transform: `translate(${p.x - end.x}px, ${p.y - end.y}px)${tilt}`,
      opacity: extra.fadeIn && i === 0 ? 0 : 1,
    })
  })
  if (extra.fadeIn && frames.length >= 2) {
    const first = frames[0] as Keyframe
    frames.splice(1, 0, { ...first, offset: Math.min(0.2, (frames[1]?.offset as number) || 0.2), opacity: 1 })
  }
  return frames
}

export const STAMP: Keyframe[] = [
  { transform: 'rotate(-6deg) scale(1.7)', opacity: 0 },
  { transform: 'rotate(-6deg) scale(1)', opacity: 1 },
]

export const POP: Keyframe[] = [
  { transform: 'scale(1.8)', opacity: 0 },
  { transform: 'scale(1)', opacity: 1 },
]
