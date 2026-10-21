import type { ApprovalStepView } from '../../api/types'
import { formatDayAndTime } from '../../ui/format'

export type StandingKind = 'waiting' | 'approved' | 'declined'

export interface Standing {
  kind: StandingKind
  headline: string
  detail: string | null
}

function names(ids: readonly string[], nameOf: (id: string) => string): string {
  const unique = [...new Set(ids.map(nameOf))]
  return unique.length > 1 ? `${unique.slice(0, -1).join(', ')} and ${unique.at(-1)}` : (unique[0] ?? 'an Approver')
}

function latest(steps: readonly ApprovalStepView[]): string | null {
  const times = steps.flatMap((step) => (step.decided_at ? [step.decided_at] : []))
  return times.length > 0 ? times.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b)) : null
}

/** Where one approval stands, in the words the card shows. A decline outranks everything because it ends the request. */
export function standingOf(steps: readonly ApprovalStepView[], nameOf: (id: string) => string): Standing {
  const declined = steps.find((step) => step.status === 'declined')
  if (declined) {
    const at = declined.decided_at
    return {
      kind: 'declined',
      headline: `Declined by ${names([declined.decided_by ?? ''], nameOf)}`,
      detail: at ? formatDayAndTime(at) : null,
    }
  }

  const approved = steps.filter((step) => step.status === 'approved')
  if (steps.length > 0 && approved.length === steps.length) {
    const at = latest(steps)
    return {
      kind: 'approved',
      headline: `Approved by ${names(approved.map((step) => step.decided_by ?? ''), nameOf)}`,
      detail: at ? formatDayAndTime(at) : null,
    }
  }

  const open = steps.find((step) => step.status === 'open') ?? steps.find((step) => step.status === 'waiting')
  const next = open ? `${open.label} decides.` : null
  const earlier =
    approved.length > 0
      ? `Step ${approved.length} of ${steps.length} approved by ${names(approved.map((step) => step.decided_by ?? ''), nameOf)}.`
      : null
  return {
    kind: 'waiting',
    headline: 'Waiting for an Approver',
    detail: [earlier, next].filter((part) => part !== null).join(' ') || null,
  }
}
