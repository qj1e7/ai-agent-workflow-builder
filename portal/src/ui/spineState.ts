export type SpineState =
  | { kind: 'not_reached' }
  | { kind: 'working' }
  | { kind: 'waiting'; waited?: string }
  | { kind: 'done' }
  | { kind: 'approved'; by: string }
  | { kind: 'declined'; by: string }
  | { kind: 'failed' }
  | { kind: 'not_needed' }

export function spineStateWords(state: SpineState): string {
  switch (state.kind) {
    case 'not_reached':
      return 'Not reached'
    case 'working':
      return 'Working'
    case 'waiting':
      return state.waited ? `Waiting for an Approver, ${state.waited}` : 'Waiting for an Approver'
    case 'done':
      return 'Done'
    case 'approved':
      return `Approved by ${state.by}`
    case 'declined':
      return `Declined by ${state.by}`
    case 'failed':
      return 'Stopped here'
    case 'not_needed':
      return 'Not needed'
  }
}

export function isCompleted(state: SpineState): boolean {
  return state.kind === 'done' || state.kind === 'approved'
}

export function isCurrent(state: SpineState): boolean {
  return state.kind === 'working' || state.kind === 'waiting' || state.kind === 'failed'
}
