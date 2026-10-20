import { formatDuration } from '../ui/format'
import type { Ms } from './brand'
import { openStep, ticketLife, type RoomState } from './room'

/** The room's state in words for a screen reader, since the drawn room is aria-hidden. waitedMs is the frame's open wait, the number the seat shows. */
export function describeRoom(room: RoomState, waitedMs: Ms | null): string {
  const names = [...room.agents.map((seat) => seat.display), ...(room.starter ? [room.starter.display] : [])]
  const sentences: string[] = []
  if (room.phase.name === 'empty') return 'The room is empty. The run has not started.'
  sentences.push(names.length > 0 ? `In the room: ${names.join(', ')}.` : 'The room is empty.')
  const open = openStep(room)
  switch (room.phase.name) {
    case 'pending':
      sentences.push('The run is starting.')
      break
    case 'working':
      sentences.push('The agents are working.')
      break
    case 'proposed':
      sentences.push('A write has been proposed and lies on the table.')
      break
    case 'awaiting_approval':
      if (open && waitedMs !== null) sentences.push(`Waiting for an Approver (${open.label}) for ${formatDuration(waitedMs)}.`)
      else sentences.push('Waiting for an Approver.')
      break
    case 'acting':
      sentences.push('An Approver said yes. The write is going through the door.')
      break
    case 'succeeded':
      sentences.push(room.phase.outcome === 'written' ? 'The run succeeded.' : 'The run succeeded with nothing to write.')
      break
    case 'rejected':
      sentences.push(`${room.phase.by.display} declined. The run stopped.`)
      break
    case 'failed':
      sentences.push(room.phase.retryable ? 'The run stopped with a problem. It can be retried.' : 'The run stopped with a problem.')
      break
  }
  const life = ticketLife(room)
  const reference = room.ticket?.lines.find((line) => line.reference)?.reference
  sentences.push(life === 'written' && reference ? `Written as ${reference}.` : 'Nothing has been written.')
  return sentences.join(' ')
}
