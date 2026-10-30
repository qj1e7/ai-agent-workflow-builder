import { ApiError } from '../../api/client'
import { connectorLabel, starterName } from '../../api/labels'
import type { ApprovalItem, ConfirmationItem, DraftItem, HomeOut, StoppedItem, WaitingItem } from '../../api/types'
import { count, withCurrentNames } from '../run/words'
import { lineWhen, runWhen, workflowPath } from '../workflows/workflow'

export const NEEDS_SHOWN = 10
const DRAFT_STEPS = 4

export type Need =
  | { readonly kind: 'approval'; readonly key: string; readonly at: string; readonly item: ApprovalItem }
  | { readonly kind: 'confirmation'; readonly key: string; readonly at: string; readonly item: ConfirmationItem }
  | { readonly kind: 'stopped'; readonly key: string; readonly at: string; readonly item: StoppedItem }

export interface LeftOut {
  readonly approvals: number
  readonly others: number
}

export interface Needs {
  readonly shown: readonly Need[]
  readonly total: number
  readonly more: LeftOut
}

const KIND_ORDER: Record<Need['kind'], number> = { approval: 0, confirmation: 1, stopped: 2 }

const urgentFirst = (a: Need, b: Need) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || b.at.localeCompare(a.at) || a.key.localeCompare(b.key)

export function needsOf(home: HomeOut): Needs {
  const all: Need[] = [
    ...home.approvals.map((item): Need => ({ kind: 'approval', key: `approval:${item.approval_id}`, at: item.started_at, item })),
    ...home.confirmations.map((item): Need => ({ kind: 'confirmation', key: `confirmation:${item.confirmation_id}`, at: item.asked_at, item })),
    ...home.stopped.map((item): Need => ({ kind: 'stopped', key: `stopped:${item.run_id}`, at: item.stopped_at, item })),
  ].sort(urgentFirst)
  const shown = all.slice(0, NEEDS_SHOWN)
  const total = home.approvals_total + home.confirmations.length + home.stopped_total
  const approvalsShown = shown.filter((need) => need.kind === 'approval').length
  const approvals = home.approvals_total - approvalsShown
  return { shown, total, more: { approvals, others: total - shown.length - approvals } }
}

export function leadLine(total: number, workflows: number): string {
  if (total === 1) return '1 thing needs you. Everything else is running.'
  if (total > 1) return `${total} things need you. Everything else is running.`
  return workflows === 0
    ? 'Nothing needs you yet. When a workflow wants to change something, it shows up here and in Teams.'
    : 'Nothing needs you right now. Your workflows are running.'
}

export function moreWords({ approvals, others }: LeftOut): string | null {
  const left = approvals + others
  if (left === 0) return null
  if (others === 0) return `${count(approvals, 'more run')} ${approvals === 1 ? 'is' : 'are'} waiting for your yes. The next ones show here as you decide these.`
  return `${left} more ${left === 1 ? 'thing needs' : 'things need'} you. The next ones show here as you finish these.`
}

export type Tone = 'wait' | 'bad' | 'tool'

export interface ItemWords {
  readonly tone: Tone
  readonly title: string
  readonly meta: string
  readonly lines: readonly string[]
  readonly note: string | null
  readonly why: string | null
}

function approvalWords(item: ApprovalItem, now: Date): ItemWords {
  const tickets = item.first_changes.length > 0 && item.first_changes.every((change) => change.operation === 'create_ticket')
  const title = item.changes === 0 ? 'A run is waiting for your yes' : `${count(item.changes, tickets ? 'ticket' : 'change')} ${item.changes === 1 ? 'is' : 'are'} waiting for your yes`
  const step = item.steps > 1 ? ` · Step ${item.step + 1} of ${item.steps}` : ''
  const lines = item.first_changes.map((change) => change.title ?? `A change in ${connectorLabel(change.connector)}`)
  const unlisted = item.changes - item.first_changes.length
  return {
    tone: 'wait',
    title,
    meta: `${item.use_case_name} · Started by ${starterName(item.started_by_name, item.trigger)}, ${runWhen(item.started_at, now)}${step}`,
    lines: unlisted > 0 ? [...lines, `and ${unlisted} more`] : lines,
    note: null,
    why: null,
  }
}

function confirmationWords(item: ConfirmationItem, now: Date): ItemWords {
  if (item.kind === 'approver') {
    return {
      tone: 'tool',
      title: `Confirm ${item.about_name ?? 'a new person'} as an Approver`,
      meta: `Asked by ${item.asked_by_name}, ${runWhen(item.asked_at, now)}`,
      lines: [],
      note: 'Approvers can say yes to changes in Jira, Teams and other systems.',
      why: null,
    }
  }
  return {
    tone: 'tool',
    title: 'Confirm a new AI model address',
    meta: `${item.summary} · Asked by ${item.asked_by_name}`,
    lines: [],
    note: 'Agents would send their prompts to this address. Until you confirm it, runs keep using the current model.',
    why: null,
  }
}

function stoppedWords(item: StoppedItem, now: Date): ItemWords {
  return {
    tone: 'bad',
    title: `${item.use_case_name} stopped`,
    meta: runWhen(item.stopped_at, now),
    lines: [],
    note: null,
    why: withCurrentNames(`${item.advice.explanation} ${item.advice.suggestion}`),
  }
}

export function wordsOf(need: Need, now: Date): ItemWords {
  switch (need.kind) {
    case 'approval':
      return approvalWords(need.item, now)
    case 'confirmation':
      return confirmationWords(need.item, now)
    case 'stopped':
      return stoppedWords(need.item, now)
  }
}

export type Action = { readonly kind: 'open'; readonly label: string; readonly to: string } | { readonly kind: 'retry'; readonly label: string; readonly runId: string }

export function actionsOf(need: Need): readonly Action[] {
  switch (need.kind) {
    case 'approval':
      return [{ kind: 'open', label: 'Review and decide', to: `/runs/${need.item.run_id}` }]
    case 'confirmation':
      return [{ kind: 'open', label: 'Review in Settings', to: need.item.kind === 'approver' ? '/settings?tab=people' : '/settings' }]
    case 'stopped':
      return need.item.retryable
        ? [
            { kind: 'retry', label: 'Retry the run', runId: need.item.run_id },
            { kind: 'open', label: 'See the run', to: `/runs/${need.item.run_id}` },
          ]
        : [{ kind: 'open', label: 'See why it stopped', to: `/runs/${need.item.run_id}` }]
  }
}

const noLongerStopped = (error: unknown) => error instanceof ApiError && error.status === 409

export function retryProblem(error: unknown, words: (error: unknown) => string): string {
  if (noLongerStopped(error)) return 'It can’t be retried now. Someone may have retried it already, so look at the run.'
  return `Could not retry the run. ${words(error)}`
}

export interface RowWords {
  readonly name: string
  readonly sub: string
}

function whyNotYours(item: WaitingItem): string {
  switch (item.because) {
    case 'started':
      return item.trigger === 'schedule' ? 'Your schedule started it' : 'You started it'
    case 'retried':
      return 'You retried it'
    case 'owns':
      return 'It is your workflow'
    case 'decided_earlier':
      return `You said yes to step ${item.step} of ${item.steps}`
  }
}

export function waitingWords(item: WaitingItem, now: Date): RowWords & { readonly to: string } {
  return {
    name: `${item.because === 'decided_earlier' ? 'Another' : 'An'} Approver’s yes on ${item.use_case_name}`,
    sub: `${whyNotYours(item)} · ${lineWhen(item.started_at, now)}`,
    to: `/runs/${item.run_id}`,
  }
}

export function draftWords(draft: DraftItem, now: Date): RowWords {
  return { name: draft.name ?? 'New workflow', sub: `Step ${draft.step} of ${DRAFT_STEPS}. Last saved ${runWhen(draft.saved_at, now)}.` }
}

export interface Next {
  readonly name: string
  readonly to: string
  readonly when: string
  readonly more: number
}

export function comingUpOf(home: HomeOut, now: Date): Next | null {
  const next = home.coming_up
  if (!next) return null
  return { name: next.name, to: workflowPath(next), when: runWhen(next.next_run_at, now), more: next.more }
}

export const HOW_IT_WORKS: readonly (readonly [string, string])[] = [
  ['Describe a task', 'In plain English, the way you would ask a colleague.'],
  ['Check what was understood', 'Fix anything that doesn’t match, then choose when it runs.'],
  ['Say yes in Teams', 'Nothing changes in Jira or Confluence until an Approver agrees.'],
  ['See the result here', 'If something stops, the AI troubleshooter tells you why.'],
]
