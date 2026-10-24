import type { RunView } from '../../api/types'
import type { DecisionPanel } from './decisionState'

export type TicketStatus =
  | { kind: 'draft' }
  | { kind: 'writing' }
  | { kind: 'written'; key: string }
  | { kind: 'declined' }

/** index is the action's place in the proposal: the platform writes the actions in that order. */
export function ticketStatus(panel: DecisionPanel, run: RunView | undefined, index = 0): TicketStatus {
  if (panel.kind !== 'decided') return { kind: 'draft' }
  if (panel.verdict === 'decline') return { kind: 'declined' }
  const key = run?.state === 'succeeded' ? run.written[index]?.external_reference : undefined
  return key ? { kind: 'written', key } : { kind: 'writing' }
}
