import type { LiveView } from './live'

/** What the transport says about the playback, and the outcome once a settled run is fully shown. */
export type Status = 'live' | 'catching_up' | 'replay' | 'done' | 'declined' | 'stopped'

export function statusOf(view: Pick<LiveView, 'frame' | 'room' | 'transport'>): Status {
  const { frame, room, transport } = view
  if (transport.settled && transport.atEdge && frame.shown === frame.head) {
    if (room.phase.name === 'failed') return 'stopped'
    if (room.phase.name === 'rejected') return 'declined'
    return 'done'
  }
  if (frame.label === 'live') return frame.shown < frame.head ? 'catching_up' : 'live'
  return 'replay'
}
