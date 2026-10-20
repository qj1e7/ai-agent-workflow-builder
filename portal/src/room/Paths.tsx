import type { Anchor, BeatView, Point, RoomLayout, RoomState } from '../run'
import { cx } from '../ui/cx'
import styles from './Room.module.css'

interface PathsProps {
  layout: RoomLayout
  room: RoomState
  beat: BeatView | null
  motion: boolean
}

export function pointAt(path: readonly Point[], t: number): Point {
  if (path.length === 0) return { x: 0, y: 0 }
  if (path.length === 1) return path[0] as Point
  const lengths: number[] = []
  let total = 0
  for (let i = 1; i < path.length; i += 1) {
    const a = path[i - 1] as Point
    const b = path[i] as Point
    const length = Math.hypot(b.x - a.x, b.y - a.y)
    lengths.push(length)
    total += length
  }
  let target = Math.max(0, Math.min(1, t)) * total
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

const toPoints = (path: readonly Point[]) => path.map((p) => `${p.x},${p.y}`).join(' ')

/** The route a beat's move travels, if it travels at all. */
export function beatRoute(beat: BeatView | null, room: RoomState, layout: RoomLayout): { from: Anchor; to: Anchor } | null {
  if (!beat || beat.type !== 'event' || !beat.move) return null
  const move = beat.move
  const host = room.agents.find((seat) => seat.role === 'host')
  switch (move.type) {
    case 'carry':
      return { from: move.from, to: move.to }
    case 'arrive':
      return host && move.who.at === 'agent' && move.who.id !== host.id ? { from: { at: 'agent', id: host.id }, to: move.who } : null
    case 'leave':
      return host ? { from: move.who, to: { at: 'agent', id: host.id } } : null
    case 'decide':
      return layout.doors.some((door) => door.side === 'teams') ? { from: { at: 'teams' }, to: { at: 'step', index: move.step } } : null
    case 'deliver':
      return { from: { at: 'table' }, to: { at: 'door', key: move.door } }
    default:
      return null
  }
}

export function Paths({ layout, room, beat, motion }: PathsProps) {
  const route = beatRoute(beat, room, layout)
  const lingering = route && beat ? layout.route(route.from, route.to) : null
  const lingerMs = beat ? beat.durationMs + 1400 : 0
  return (
    <svg className={styles['paths']} width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} aria-hidden="true" focusable="false">
      {room.trips.map((trip) => {
        const path = layout.route({ at: 'agent', id: trip.agent }, { at: 'door', key: trip.door })
        // Marks sit on the first part of the path and the cross near the door, so the two never meet.
        const marks = Array.from({ length: trip.marks }, (_, i) => pointAt(path, (0.62 * (i + 1)) / (trip.marks + 1)))
        const fault = trip.state === 'failed' ? pointAt(path, 0.82) : null
        return (
          <g key={`${trip.agent}:${trip.step}`} className={cx(styles['trip'], styles[`trip_${trip.state}`])}>
            <polyline points={toPoints(path)} className={styles['tripLine']} />
            {marks.map((mark, i) => (
              <g key={i} className={styles['mark']} style={{ transform: `translate(${mark.x}px, ${mark.y}px)` }}>
                <circle r={10} />
                <text y={4}>{i + 1}</text>
              </g>
            ))}
            {fault ? (
              <g className={styles['fault']} style={{ transform: `translate(${fault.x}px, ${fault.y}px)` }}>
                <circle r={13} />
                <path d="M-4.5 -4.5l9 9M4.5 -4.5l-9 9" />
              </g>
            ) : null}
          </g>
        )
      })}
      {lingering && beat ? (
        <polyline
          key={beat.key}
          points={toPoints(lingering)}
          className={cx(styles['lingerLine'], !motion && styles['lingerStill'])}
          style={{ animationDuration: `${lingerMs}ms` }}
        />
      ) : null}
    </svg>
  )
}
