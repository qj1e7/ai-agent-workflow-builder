import { ApiError } from '../../api/client'
import { DRAFT_STEPS } from '../../api/drafts'
import { connectorLabel, starterName } from '../../api/labels'
import type { ApprovalItem, ConfirmationItem, DraftItem, FollowingUpItem, HomeOut, StoppedItem, WaitingItem } from '../../api/types'
import { count, withCurrentNames } from '../run/words'
import { requestKindWords, requestPath } from '../workflows/requests'
import { lineWhen, nextRunAt, runWhen, workflowPath } from '../workflows/workflow'

/** Home for an Operator shows the most urgent few. Workflows, and Home for someone who is not an Operator, show everything the platform returned. */
export const HOME_NEEDS_SHOWN = 3

export type Need =
  | { readonly kind: 'approval'; readonly key: string; readonly at: string; readonly item: ApprovalItem }
  | { readonly kind: 'confirmation'; readonly key: string; readonly at: string; readonly item: ConfirmationItem }
  | { readonly kind: 'stopped'; readonly key: string; readonly at: string; readonly item: StoppedItem }
  | { readonly kind: 'reply'; readonly key: string; readonly at: string; readonly item: FollowingUpItem }

export interface LeftOut {
  readonly approvals: number
  readonly others: number
}

export interface Needs {
  readonly shown: readonly Need[]
  readonly total: number
  readonly more: LeftOut
}

const KIND_ORDER: Record<Need['kind'], number> = { stopped: 0, approval: 1, confirmation: 2, reply: 3 }

const urgentFirst = (a: Need, b: Need) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || b.at.localeCompare(a.at) || a.key.localeCompare(b.key)

export const needsTotal = (home: HomeOut) => home.approvals_total + home.confirmations.length + home.stopped_total + home.replied.length

/** The runs Needs you on Workflows offers an action on, so the list of workflows under it need not offer the same run again. */
export const runsInNeeds = (home: HomeOut): ReadonlySet<string> =>
  new Set(needsOf(home).shown.flatMap((need) => (need.kind === 'approval' || need.kind === 'stopped' ? [need.item.run_id] : [])))

export function needsOf(home: HomeOut, limit = Infinity): Needs {
  const all: Need[] = [
    ...home.approvals.map((item): Need => ({ kind: 'approval', key: `approval:${item.approval_id}`, at: item.started_at, item })),
    ...home.confirmations.map((item): Need => ({ kind: 'confirmation', key: `confirmation:${item.confirmation_id}`, at: item.asked_at, item })),
    ...home.stopped.map((item): Need => ({ kind: 'stopped', key: `stopped:${item.run_id}`, at: item.stopped_at, item })),
    ...home.replied.map((item): Need => ({ kind: 'reply', key: `reply:${item.request_id}`, at: item.latest_reply?.replied_at ?? item.asked_at, item })),
  ].sort(urgentFirst)
  const shown = all.slice(0, limit)
  const total = needsTotal(home)
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

export const SEE_ALL_WORDS = 'See all on Workflows'

export function moreWords({ approvals, others }: LeftOut): string | null {
  const left = approvals + others
  if (left === 0) return null
  if (others === 0) return `${count(approvals, 'more run')} ${approvals === 1 ? 'is' : 'are'} waiting for your yes. The next ones show here as you decide these.`
  return `${left} more ${left === 1 ? 'thing needs' : 'things need'} you. The next ones show here as you finish these.`
}

export type Tone = 'wait' | 'bad' | 'tool' | 'info'

export interface ItemWords {
  readonly tone: Tone
  readonly title: string
  readonly meta: string
  readonly lines: readonly string[]
  readonly note: string | null
  readonly why: string | null
}

function starterOf(item: ApprovalItem): string {
  if (item.started_by_name !== null) return starterName(item.started_by_name, item.trigger)
  return item.trigger === 'schedule' ? 'a schedule' : 'someone no longer on the list'
}

function approvalWords(item: ApprovalItem, now: Date): ItemWords {
  const tickets = item.first_changes.length === item.changes && item.first_changes.every((change) => change.operation === 'create_ticket')
  const title = item.changes === 0 ? 'A run is waiting for your yes' : `${count(item.changes, tickets ? 'ticket' : 'change')} ${item.changes === 1 ? 'is' : 'are'} waiting for your yes`
  const step = item.steps > 1 ? ` · Step ${item.step + 1} of ${item.steps}` : ''
  const lines = item.first_changes.map((change) => change.title ?? `A change in ${connectorLabel(change.connector)}`)
  const unlisted = item.changes - item.first_changes.length
  return {
    tone: 'wait',
    title,
    meta: `${item.use_case_name} · Started by ${starterOf(item)}, ${runWhen(item.started_at, now)}${step}`,
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

const REPLY_SHOWN = 160

function replyWords(item: FollowingUpItem, now: Date): ItemWords {
  const reply = item.latest_reply
  const said = reply ? reply.text : ''
  return {
    tone: 'info',
    title: `${reply ? reply.replied_by_name : 'The team'} replied to your ${item.kind === 'support' ? 'report' : 'request'}`,
    meta: `${requestKindWords(item.kind)} · ${reply ? runWhen(reply.replied_at, now) : runWhen(item.asked_at, now)}`,
    lines: [],
    note: said.length > REPLY_SHOWN ? `${said.slice(0, REPLY_SHOWN - 1).trimEnd()}…` : said,
    why: null,
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
    case 'reply':
      return replyWords(need.item, now)
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
      return stoppedActions(need.item.run_id, need.item.retryable)
    case 'reply':
      return [{ kind: 'open', label: 'Read the reply', to: requestPath(need.item.request_id) }]
