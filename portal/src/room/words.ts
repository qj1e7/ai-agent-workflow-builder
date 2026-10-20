import { connectorLabel } from '../api/labels'
import { formatDuration } from '../ui/format'
import type { AgentSeat, ApprovalStep, Checker, Door, RoomState, TeamsPost, Ticket, TicketLife, Trip } from '../run'

export interface StatusWords {
  readonly text: string
  readonly tone: 'quiet' | 'live' | 'wait' | 'done' | 'fail'
}

export function agentStatus(seat: AgentSeat, speaking: boolean): StatusWords {
  if (speaking) return { text: 'Speaking', tone: 'live' }
  switch (seat.status) {
    case 'working':
      return { text: 'Working', tone: 'live' }
    case 'done':
      return { text: 'Done', tone: 'done' }
    case 'stopped':
      return { text: 'Stopped', tone: 'fail' }
    case 'present':
      if (seat.role === 'host') return { text: 'Runs the room', tone: 'quiet' }
      if (seat.role === 'troubleshooter') return { text: 'Explains the stop', tone: 'quiet' }
      return { text: 'Ready', tone: 'quiet' }
  }
}

export function stepName(step: ApprovalStep): string {
  const state = step.state
  if (state.is === 'approved' || state.is === 'declined') return state.by.display
  return step.label
}

export function stepStatus(step: ApprovalStep, waitedMs: number | null): StatusWords {
  switch (step.state.is) {
    case 'open':
      return { text: waitedMs === null ? 'Waiting' : `Waiting ${formatDuration(waitedMs)}`, tone: 'wait' }
    case 'waiting':
      return { text: `After step ${step.index}`, tone: 'quiet' }
    case 'approved':
      return { text: 'Approved', tone: 'done' }
    case 'declined':
      return { text: 'Declined', tone: 'fail' }
  }
}

export function doorName(door: Door | { readonly side: 'write'; readonly key: null; readonly label: string | null }): string {
  if (door.side === 'teams') return 'Teams'
  if (door.key === null) return door.label ?? 'Write'
  return connectorLabel(door.key)
}

export function readDoorStatus(trips: readonly Trip[], key: string): StatusWords {
  const failed = trips.some((trip) => trip.door === key && trip.state === 'failed')
  if (failed) return { text: 'Not answering', tone: 'fail' }
  return { text: 'Read only. Always open.', tone: 'quiet' }
}

export function writeDoorStatus(checker: Checker | null, approvedBy: readonly string[], written: boolean): StatusWords {
  switch (checker) {
    case 'allowed':
      return { text: approvedBy.length > 0 ? `Allowed. Approved by ${approvedBy.join(' and ')}.` : 'Allowed', tone: 'done' }
    case 'blocked':
      return { text: 'Blocked by the safety checker', tone: 'fail' }
    default:
      if (written) return { text: 'Locked again', tone: 'quiet' }
      if (approvedBy.length > 0) return { text: `Approved by ${approvedBy.join(' and ')}. Not written yet.`, tone: 'done' }
      return { text: 'Locked until an Approver says yes', tone: 'quiet' }
  }
}

export function checkerStatus(checker: Checker | null): StatusWords {
  switch (checker) {
    case 'allowed':
      return { text: 'Allowed', tone: 'done' }
    case 'blocked':
      return { text: 'Blocked', tone: 'fail' }
    default:
      return { text: 'Locked', tone: 'quiet' }
  }
}

export function teamsStatus(post: TeamsPost | null): StatusWords {
  if (!post || post.is === 'not_posted') return { text: 'Where Approvers decide', tone: 'quiet' }
  if (post.is === 'posted') return { text: post.channel, tone: 'wait' }
  return { text: 'Could not post', tone: 'fail' }
}

export interface TicketWords {
  readonly tag: string
  readonly line: string
  /** The compact ticket's one status word beside its icon, so the action line keeps every character. */
  readonly short: string
  readonly tone: StatusWords['tone']
}

export function ticketWords(ticket: Ticket, life: TicketLife): TicketWords {
  const reference = ticket.lines.find((line) => line.reference)?.reference
  switch (life) {
    case 'draft':
      return { tag: 'Draft', line: 'Not written yet', short: 'Not written', tone: 'quiet' }
    case 'waiting':
      return { tag: 'Draft', line: 'Waiting for an Approver', short: 'Waiting', tone: 'wait' }
    case 'approved':
      return { tag: 'Approved', line: 'Approved, being written', short: 'Approved', tone: 'done' }
    case 'written':
      return { tag: 'Written', line: reference ? `Written as ${reference}` : 'Written', short: reference ? `Written as ${reference}` : 'Written', tone: 'done' }
    case 'denied':
      return { tag: 'Blocked', line: 'Blocked by the safety checker', short: 'Blocked', tone: 'fail' }
    case 'declined':
      return { tag: 'Declined', line: 'Declined, nothing was written', short: 'Declined', tone: 'fail' }
  }
}

export function approvedBy(room: RoomState): string[] {
  return (room.approval?.steps ?? []).flatMap((step) => (step.state.is === 'approved' ? [step.state.by.display] : []))
}
