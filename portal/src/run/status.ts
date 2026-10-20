import type { LiveView } from './live'

export type Status = 'live' | 'sped_up' | 'catching_up' | 'replay' | 'done' | 'declined' | 'stopped'

export function statusOf(view: Pick<LiveView, 'frame' | 'room' | 'transport'>): Status {
  const { frame, room, transport } = view
  if (transport.settled && transport.atEdge && frame.shown === frame.head) {
    if (room.phase.name === 'failed') return 'stopped'
    if (room.phase.name === 'rejected') return 'declined'
    return 'done'
  }
  if (frame.catchingUp) return 'catching_up'
  if (frame.spedUp) return 'sped_up'
  return frame.label === 'live' ? 'live' : 'replay'
}
