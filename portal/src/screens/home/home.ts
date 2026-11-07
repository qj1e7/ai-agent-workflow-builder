import { ApiError } from '../../api/client'
import { DRAFT_STEPS } from '../../api/drafts'
import { andList } from './card'
import { connectorLabel, starterName } from '../../api/labels'
import type { AddressItem, CapabilitiesView, PlannerAnswerIn, ApprovalItem, ConfirmationItem, ConnectionItem, DraftItem, FollowingUpItem, HomeOut, StoppedItem, WaitingItem } from '../../api/types'
import { count, withCurrentNames } from '../run/words'
import { requestKindWords, requestPath } from '../workflows/requests'
import { movedHeadline, notFoundHeadline } from '../software/software'
import { lineWhen, nextRunAt, runWhen, workflowPath } from '../workflows/workflow'

/** Home for an Operator shows the most urgent few. Workflows, and Home for someone who is not an Operator, show everything the platform returned. */
export const HOME_NEEDS_SHOWN = 3

const CONNECTIONS_PATH = '/settings?tab=connections'

export type Need =
  | { readonly kind: 'approval'; readonly key: string; readonly at: string; readonly item: ApprovalItem }
  | { readonly kind: 'connection'; readonly key: string; readonly at: string; readonly item: ConnectionItem }
  | { readonly kind: 'address'; readonly key: string; readonly at: string; readonly item: AddressItem }
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

const KIND_ORDER: Record<Need['kind'], number> = { stopped: 0, approval: 1, connection: 2, address: 3, confirmation: 4, reply: 5 }

const urgentFirst = (a: Need, b: Need) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || b.at.localeCompare(a.at) || a.key.localeCompare(b.key)

export const needsTotal = (home: HomeOut) => home.approvals_total + home.confirmations.length + home.stopped_total + home.connections.length + home.addresses.length + home.replied.length

/** The runs Needs you on Workflows offers an action on, so the list of workflows under it need not offer the same run again. */
export const runsInNeeds = (home: HomeOut): ReadonlySet<string> =>
  new Set(needsOf(home).shown.flatMap((need) => (need.kind === 'approval' || need.kind === 'stopped' ? [need.item.run_id] : [])))

export function needsOf(home: HomeOut, limit = Infinity): Needs {
  const all: Need[] = [
    ...home.approvals.map((item): Need => ({ kind: 'approval', key: `approval:${item.approval_id}`, at: item.started_at, item })),
    ...home.connections.map((item): Need => ({ kind: 'connection', key: `connection:${item.id}`, at: item.checked_at ?? '', item })),
    ...home.addresses.map((item): Need => ({ kind: 'address', key: `address:${item.software_id}`, at: item.checked_at ?? '', item })),
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

/** The one line under the greeting. It never repeats the count, because Needs you under it carries that. */
export function stateLine(home: HomeOut, now: Date): string {
  const total = needsTotal(home)
  if (total > 0) return total === 1 ? 'Something needs you.' : 'Some things need you.'
  const next = comingUpOf(home, now)
  return next ? `Nothing needs you. Next up: ${next.name}, ${next.when}.` : 'Nothing needs you. Nothing is scheduled yet.'
}

/** The line under an Approver’s greeting. An Approver has no box, so it says what waits for a yes. */
export function approverLine(home: HomeOut): string {
  const total = needsTotal(home)
  if (total === 0) return 'Nothing needs you right now.'
  if (total === home.approvals_total) return `${count(total, 'request')} ${total === 1 ? 'is' : 'are'} waiting for your yes.`
  return total === 1 ? '1 thing needs you.' : `${total} things need you.`
}

export interface Suggestion {
  readonly label: string
  readonly ask: PlannerAnswerIn
}

/**
 * The three chips under the box, chosen from what is going on now. A chip sends an intent, which never asks the model.
 * Day one offers the platform’s own examples instead, and a typed example does ask the model.
 */
export function suggestionsOf(home: HomeOut, capabilities: CapabilitiesView | undefined): readonly Suggestion[] {
  if (home.workflows === 0) {
    return (capabilities?.examples ?? []).map((example) => ({
      label: example.text,
      ask: example.kind === 'learn' ? { intent: 'abilities' } : { text: example.text },
    }))
  }
  const first = needsOf(home, 1).shown[0]
  const stopped = home.stopped.find((item) => first?.key !== `stopped:${item.run_id}`)
  return [
    { label: 'Check my workflows', ask: { intent: 'check_workflows' } },
    stopped
      ? { label: `Why did ${stopped.use_case_name} stop?`, ask: { intent: 'why_stopped', use_case_id: stopped.use_case_id } }
      : { label: 'What can I ask for?', ask: { intent: 'abilities' } },
    { label: 'Set up another workflow', ask: { intent: 'setup_ideas' } },
  ]
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

function connectionWords(item: ConnectionItem, now: Date): ItemWords {
  const down = item.state !== 'working'
  return {
    tone: down ? 'bad' : 'wait',
    title: item.problem ?? `${item.name} needs attention`,
    meta: item.last_ok_at ? `${item.name} · Last seen working ${runWhen(item.last_ok_at, now)}` : item.name,
    lines: [],
    note: item.fix,
    why: null,
  }
}

function addressWords(item: AddressItem): ItemWords {
  return {
    tone: 'bad',
    title: item.moved_to ? movedHeadline(item.name, item.repo, item.moved_to) : notFoundHeadline(item.name, item.repo),
    meta: `Software watchlist · ${item.name}`,
    lines: [],
    note: item.moved_to ? 'Only our list changes if you use the new address.' : 'It may have moved to another repository. Remove it and add it again at its new address.',
    why: null,
  }
}

function stoppedWords(item: StoppedItem, now: Date, modelOff: boolean): ItemWords {
  return {
    tone: 'bad',
    title: `${item.use_case_name} stopped`,
    meta: runWhen(item.stopped_at, now),
    lines: [],
    note: item.retryable && modelOff ? CAN_RUN_AGAIN : null,
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

export function wordsOf(need: Need, now: Date, modelOff = false): ItemWords {
  switch (need.kind) {
    case 'approval':
      return approvalWords(need.item, now)
    case 'connection':
      return connectionWords(need.item, now)
    case 'address':
      return addressWords(need.item)
    case 'confirmation':
      return confirmationWords(need.item, now)
    case 'stopped':
      return stoppedWords(need.item, now, modelOff)
    case 'reply':
      return replyWords(need.item, now)
  }
}

export type Action =
  | { readonly kind: 'open'; readonly label: string; readonly to: string }
  | { readonly kind: 'retry'; readonly label: string; readonly runId: string }

export function actionsOf(need: Need, modelOff = false): readonly Action[] {
  switch (need.kind) {
    case 'approval':
      return [{ kind: 'open', label: 'Review and decide', to: `/runs/${need.item.run_id}` }]
    case 'connection':
      return [{ kind: 'open', label: 'See it in Settings', to: CONNECTIONS_PATH }]
    case 'address':
      return [{ kind: 'open', label: 'Show it on the watchlist', to: `/software?row=${encodeURIComponent(need.item.software_id)}` }]
    case 'confirmation':
      return [{ kind: 'open', label: 'Review in Settings', to: need.item.kind === 'approver' ? '/settings?tab=people' : '/settings?tab=model' }]
    case 'stopped':
      return stoppedActions(need.item.run_id, need.item.retryable, modelOff)
    case 'reply':
      return [{ kind: 'open', label: 'Read the reply', to: requestPath(need.item.request_id) }]
  }
}

export const CAN_RUN_AGAIN = 'Can run again once an AI model is connected.'

/**
 * A stopped run offers Retry when the platform says it can be retried, and always a way to read why it stopped.
 * With no AI model a retry would fail again, so the run waits and only the reading stays (spec 5.4).
 */
export function stoppedActions(runId: string, retryable: boolean, modelOff = false): readonly Action[] {
  if (retryable && modelOff) return [{ kind: 'open', label: 'See the run', to: `/runs/${runId}` }]
  return retryable
    ? [
        { kind: 'retry', label: 'Retry the run', runId },
        { kind: 'open', label: 'See the run', to: `/runs/${runId}` },
      ]
    : [{ kind: 'open', label: 'See why it stopped', to: `/runs/${runId}` }]
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
      return 'You already said yes to an earlier step'
  }
}

export function waitingWords(item: WaitingItem, now: Date): RowWords & { readonly to: string } {
  return {
    name: `${item.because === 'decided_earlier' ? 'Another' : 'An'} Approver’s yes on ${item.use_case_name}`,
    sub: `${whyNotYours(item)} · ${lineWhen(item.started_at, now)}`,
    to: `/runs/${item.run_id}`,
  }
}

/** `left` is what setupLeft says still stops the saved card, or null when the draft holds no card (an old four-step draft, or only words). */
export function draftWords(draft: DraftItem, now: Date, left?: readonly string[] | null): RowWords {
  const saved = `Last saved ${runWhen(draft.saved_at, now)}.`
  const why = left === undefined ? (draft.step === null ? '' : `Step ${draft.step} of ${DRAFT_STEPS}. `) : left === null ? 'Only your words are saved. ' : left.length > 0 ? `Needs ${andList(left)}. ` : 'Nothing is unclear. '
  return { name: draft.name ?? 'New workflow', sub: `${why}${saved}` }
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
  return { name: next.name, to: workflowPath(next), when: nextRunAt(next.next_run_at, now, next.time_zone), more: next.more }
}
