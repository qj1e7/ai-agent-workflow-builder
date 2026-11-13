import { ApiError } from '../../api/client'
import { andList, crossedWords, type Left } from './card'
import { connectorLabel, starterName } from '../../api/labels'
import type { AddressItem, CapabilitiesView, PlannerAnswerIn, ApprovalItem, ConfirmationItem, ConnectionItem, DeclinedItem, DraftItem, FollowingUpItem, HomeOut, QuestionItem, StoppedItem, WaitingItem } from '../../api/types'
import { count, declineTail, withCurrentNames } from '../run/words'
import { requestKindWords, requestPath } from '../workflows/requests'
import { movedHeadline, notFoundHeadline, softwarePath } from '../software/software'
import { lineWhen, runWhen } from '../workflows/workflow'
import type { PanelItem } from '../../ui/sidePanel'

/** Home for an Operator shows the most urgent five, then “N more”. Workflows, and Home for someone who is not an Operator, show everything the platform returned. */
export const HOME_NEEDS_SHOWN = 5

const CONNECTIONS_PATH = '/settings?tab=connections'

export type Need =
  | { readonly kind: 'approval'; readonly key: string; readonly at: string; readonly item: ApprovalItem }
  | { readonly kind: 'connection'; readonly key: string; readonly at: string; readonly item: ConnectionItem }
  | { readonly kind: 'address'; readonly key: string; readonly at: string; readonly item: AddressItem }
  | { readonly kind: 'confirmation'; readonly key: string; readonly at: string; readonly item: ConfirmationItem }
  | { readonly kind: 'stopped'; readonly key: string; readonly at: string; readonly item: StoppedItem }
  | { readonly kind: 'declined'; readonly key: string; readonly at: string; readonly item: DeclinedItem }
  | { readonly kind: 'question'; readonly key: string; readonly at: string; readonly item: QuestionItem }
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

const KIND_ORDER: Record<Need['kind'], number> = { stopped: 0, approval: 1, question: 2, declined: 3, connection: 4, address: 5, confirmation: 6, reply: 7 }

/** Needs you is grouped wherever it is listed in full (spec 3.5): what to do now, then what to set up. */
export type NeedGroup = 'now' | 'set'

export const NEED_GROUPS: readonly (readonly [NeedGroup, string])[] = [
  ['now', 'Do now'],
  ['set', 'Set up'],
]

/**
 * Stops, approvals, declined test runs and replies are Do now, and so is a connection that doesn't work, because it stops every run (no AI model,
 * Jira not answering). A key that still works but runs out soon, software whose address moved, and confirmations are Set up.
 */
export function groupOf(need: Need): NeedGroup {
  switch (need.kind) {
    case 'stopped':
    case 'approval':
    case 'declined':
    case 'question':
    case 'reply':
      return 'now'
    case 'connection':
      return need.item.state === 'working' ? 'set' : 'now'
    case 'address':
    case 'confirmation':
      return 'set'
  }
}

const GROUP_ORDER: Record<NeedGroup, number> = { now: 0, set: 1 }

/** No AI model leads Do now, as in the prototype, because nothing that needs the model can run until it is connected. */
const rankOf = (need: Need): number => (need.kind === 'connection' && noModel(need.item) ? -1 : KIND_ORDER[need.kind])

const urgentFirst = (a: Need, b: Need) =>
  GROUP_ORDER[groupOf(a)] - GROUP_ORDER[groupOf(b)] || rankOf(a) - rankOf(b) || b.at.localeCompare(a.at) || a.key.localeCompare(b.key)

export const needsTotal = (home: HomeOut) =>
  home.approvals_total +
  home.confirmations.length +
  home.stopped_total +
  home.declined_total +
  home.questions_for_me_total +
  home.connections.length +
  home.addresses.length +
  home.replied.length

/** The runs Needs you on Workflows offers an action on, so the list of workflows under it need not offer the same run again. */
export const runsInNeeds = (home: HomeOut): ReadonlySet<string> =>
  new Set(needsOf(home).shown.flatMap((need) => (need.kind === 'approval' || need.kind === 'stopped' ? [need.item.run_id] : [])))

/** The list Needs you is made from: Do now before Set up, and inside each group the most urgent first. */
export function needsOf(home: HomeOut, limit = Infinity): Needs {
  const all: Need[] = [
    ...home.approvals.map((item): Need => ({ kind: 'approval', key: `approval:${item.approval_id}`, at: item.started_at, item })),
    ...home.connections.map((item): Need => ({ kind: 'connection', key: `connection:${item.id}`, at: item.checked_at ?? '', item })),
    ...home.addresses.map((item): Need => ({ kind: 'address', key: `address:${item.software_id}`, at: item.checked_at ?? '', item })),
    ...home.confirmations.map((item): Need => ({ kind: 'confirmation', key: `confirmation:${item.confirmation_id}`, at: item.asked_at, item })),
    ...home.stopped.map((item): Need => ({ kind: 'stopped', key: `stopped:${item.run_id}`, at: item.stopped_at, item })),
    ...home.declined.map((item): Need => ({ kind: 'declined', key: `declined:${item.run_id}`, at: item.declined_at, item })),
    ...home.questions_for_me.map((item): Need => ({ kind: 'question', key: `question:${item.question_id}`, at: item.asked_at, item })),
    ...home.replied.map((item): Need => ({ kind: 'reply', key: `reply:${item.request_id}`, at: item.latest_reply?.replied_at ?? item.asked_at, item })),
  ].sort(urgentFirst)
  const shown = all.slice(0, limit)
  const total = needsTotal(home)
  const approvalsShown = shown.filter((need) => need.kind === 'approval').length
  const approvals = home.approvals_total - approvalsShown
  return { shown, total, more: { approvals, others: total - shown.length - approvals } }
}

/** The requests waiting for this person’s yes, from the same list as Needs you, so the two never disagree. */
export function approvalsOf(home: HomeOut): Needs {
  const shown = needsOf(home).shown.filter((need) => need.kind === 'approval')
  return { shown, total: home.approvals_total, more: { approvals: home.approvals_total - shown.length, others: 0 } }
}

/** What waits for the yes of someone who isn’t an Operator, in the sketch’s words, for the chat’s answer and, with no full stop, his Home’s heading. */
export function approverLine(home: HomeOut): string {
  const total = needsTotal(home)
  if (total === 0) return 'Nothing waits for your yes.'
  if (total === home.approvals_total) return `${count(total, 'change')} ${total === 1 ? 'waits' : 'wait'} for your yes.`
  return total === 1 ? '1 thing needs you.' : `${total} things need you.`
}

/** His Home’s heading: the same words as his answer, as a heading. */
export const approverHeading = (home: HomeOut): string => approverLine(home).replace(/\.$/, '')

export interface Suggestion {
  readonly label: string
  readonly ask: PlannerAnswerIn
  /** Answered on the page from the watchlist, with no model, instead of going to the Planner. */
  readonly local?: 'behind'
}

/** The sketch’s three chips for someone who isn’t an Operator. Each is an intent, so none asks the model. */
export const APPROVER_SUGGESTIONS: readonly Suggestion[] = [
  { label: 'What waits for me?', ask: { intent: 'needs_me' } },
  { label: 'What did I decide?', ask: { intent: 'decided' } },
  { label: 'What can you do?', ask: { intent: 'abilities' } },
]

/** The sketch’s three once software is on the watchlist. None asks the model: two are intents the platform answers, and the middle one is read from the watchlist itself. */
const WATCHED_CHIPS: readonly Suggestion[] = [
  { label: 'What needs me?', ask: { intent: 'needs_me' } },
  { label: 'Which software is behind?', ask: { text: 'Which software has a newer version?' }, local: 'behind' },
  { label: 'What can you do?', ask: { intent: 'abilities' } },
]

/**
 * The chips under the box. The team’s focus is software versioning (8 Nov 2026), so they are about the watchlist. With none
 * watched, they are the platform’s own examples, where “What can you do?” is an intent. Until the watchlist has loaded there are
 * none, so the set never flips.
 */
export function suggestionsOf(watched: number | undefined, capabilities: CapabilitiesView | undefined): readonly Suggestion[] {
  if (watched === undefined) return []
  if (watched > 0) return WATCHED_CHIPS
  return (capabilities?.examples ?? []).map((example) => ({
    label: example.text,
    ask: example.kind === 'learn' ? { intent: 'abilities' } : { text: example.text },
  }))
}

export const SEE_ALL_WORDS = 'See all on Workflows'

export function moreWords({ approvals, others }: LeftOut): string | null {
  const left = approvals + others
  if (left === 0) return null
  if (others === 0) return `${count(approvals, 'more run')} ${approvals === 1 ? 'is' : 'are'} waiting for your yes. The next ones show here as you decide these.`
  return `${left} more ${left === 1 ? 'thing needs' : 'things need'} you. The next ones show here as you finish these.`
}

export type Tone = 'wait' | 'bad' | 'tool' | 'info' | 'off'

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

/** The platform lists the AI model while none is set up. Without it the Planner and every agent workflow stop, so the row says so. */
const noModel = (item: ConnectionItem): boolean => item.id === 'model' && item.state === 'not_set_up'

const NO_MODEL: ItemWords = {
  tone: 'bad',
  title: 'No AI model connected',
  meta: 'Settings, AI model',
  lines: [],
  note: 'Until a model is connected, the Planner can’t read new requests and agent workflows can’t run. Only the Software watchlist keeps going, with a simple summary.',
  why: null,
}

function connectionWords(item: ConnectionItem, now: Date): ItemWords {
  if (noModel(item)) return NO_MODEL
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

/** The person's own test run an Approver declined, with the rest of the declined record under it (spec 10.5). */
function declinedWords(item: DeclinedItem, now: Date, modelOff: boolean): ItemWords {
  const tail = declineTail({ reason: item.decline_reason })
  return {
    tone: 'off',
    title: `${item.declined_by_name ?? 'An Approver'} declined your test run`,
    meta: `${item.use_case_name} · ${runWhen(item.declined_at, now)}`,
    lines: [],
    note: modelOff ? `${tail} ${CAN_TEST_AGAIN}` : tail,
    why: null,
  }
}

/** An Approver's question on a request this person made, which waits for their answer (spec 10.4). */
function questionWords(item: QuestionItem): ItemWords {
  return {
    tone: 'info',
    title: `${item.asked_by_name ?? 'An Approver'} asked you about ${item.use_case_name}`,
    meta: 'The request is still waiting for a yes',
    lines: [],
    note: `“${item.text}”`,
    why: null,
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
    case 'declined':
      return declinedWords(need.item, now, modelOff)
    case 'question':
      return questionWords(need.item)
    case 'reply':
      return replyWords(need.item, now)
  }
}

/** A row’s dot: red when something broke, amber when something waits on the person. */
export type LineTone = 'err' | 'wait'

/** One row of Needs you as the sketch writes it: what it is about in bold, then what happened, with a shorter form for the strip. */
export interface NeedLine {
  readonly tone: LineTone
  readonly subject: string
  readonly rest: string
  readonly short: string
}

const CONNECTION_STATE: Record<ConnectionItem['state'], string> = {
  working: 'needs attention',
  needs_attention: 'needs attention',
  not_answering: 'isn’t answering',
  not_set_up: 'isn’t set up',
  not_checked: 'hasn’t been checked',
}

/** "at 10:14" today, else "Wed 4 Nov at 10:14". */
const atWhen = (iso: string, now: Date): string => runWhen(iso, now).replace(/^Today, /, 'at ').replace(/^(.+), (\d+:\d+)$/, '$1 at $2')

/** "today", else the day, such as "Wed 18 Nov". */
export const onDay = (iso: string, now: Date): string => {
  const day = lineWhen(iso, now)
  return day.startsWith('Today') ? 'today' : day
}

const line = (tone: LineTone, subject: string, rest: string, short = rest): NeedLine => ({ tone, subject, rest, short })

function connectionLine(item: ConnectionItem, now: Date): NeedLine {
  if (item.state === 'working' && item.expires_at) return line('wait', `${item.name} key`, `expires ${onDay(item.expires_at, now)}`)
  return line(item.state === 'working' ? 'wait' : 'err', item.name, CONNECTION_STATE[item.state])
}

export function lineOf(need: Need, now: Date): NeedLine {
  switch (need.kind) {
    case 'stopped':
      return line('err', need.item.use_case_name, `stopped ${atWhen(need.item.stopped_at, now)}`, 'stopped')
    case 'approval':
      return line('wait', need.item.use_case_name, 'needs your yes')
    case 'connection':
      return connectionLine(need.item, now)
    case 'address':
      return need.item.moved_to
        ? line('wait', need.item.name, `moved to ${need.item.moved_to} on GitHub`, 'moved')
        : line('wait', need.item.name, 'can’t be found on GitHub', 'not found')
    case 'confirmation':
      return need.item.kind === 'approver'
        ? line('wait', need.item.about_name ?? 'A new person', 'waits to be confirmed as an Approver', 'waits to be confirmed')
        : line('wait', 'A new AI model address', 'waits to be confirmed')
    case 'declined':
      return line('wait', need.item.declined_by_name ?? 'An Approver', `declined your test run of ${need.item.use_case_name}`, 'declined your test run')
    case 'question':
      return line('wait', need.item.asked_by_name ?? 'An Approver', `asked you about ${need.item.use_case_name}`, 'asked you a question')
    case 'reply':
      return line('wait', need.item.latest_reply?.replied_by_name ?? 'The team', `replied to your ${need.item.kind === 'support' ? 'report' : 'request'}`, 'replied')
  }
}

/** `item` is set when the chat opens it in the side panel. Anywhere else it opens `to`, its page. */
export type Action =
  | { readonly kind: 'open'; readonly label: string; readonly to: string; readonly item?: PanelItem }
  | { readonly kind: 'retry'; readonly label: string; readonly runId: string }
  | { readonly kind: 'test'; readonly label: string; readonly useCaseId: string }

const runItem = (runId: string): PanelItem => ({ kind: 'run', id: runId })
const approvalItem = (runId: string): PanelItem => ({ kind: 'approval', id: runId })

export function actionsOf(need: Need, modelOff = false): readonly Action[] {
  switch (need.kind) {
    case 'approval':
      return [{ kind: 'open', label: 'Review and decide', to: `/runs/${need.item.run_id}`, item: approvalItem(need.item.run_id) }]
    case 'connection':
      return noModel(need.item)
        ? [{ kind: 'open', label: 'Connect a model', to: '/settings?tab=model' }]
        : [{ kind: 'open', label: 'See it in Settings', to: CONNECTIONS_PATH, item: { kind: 'connection', id: need.item.id } }]
    case 'address':
      return [{ kind: 'open', label: 'Show it on the watchlist', to: softwarePath(need.item.software_id), item: { kind: 'software', id: need.item.software_id } }]
    case 'confirmation':
      return [{ kind: 'open', label: 'Review in Settings', to: need.item.kind === 'approver' ? '/settings?tab=people' : '/settings?tab=model' }]
    case 'stopped':
      return stoppedActions(need.item.run_id, need.item.retryable, modelOff)
    case 'declined':
      return declinedActions(need.item, modelOff)
    case 'question':
      return [{ kind: 'open', label: `Answer ${need.item.asked_by_name ?? 'the question'}`, to: `/runs/${need.item.run_id}`, item: runItem(need.item.run_id) }]
    case 'reply':
      return [{ kind: 'open', label: 'Read the reply', to: requestPath(need.item.request_id) }]
  }
}

/** Where Open on the pinned line goes: the item's own page, which is the first thing its row offers that opens a page. */
export function openPathOf(need: Need): string {
  const open = actionsOf(need).find((action) => action.kind === 'open')
  return open?.to ?? (need.kind === 'stopped' ? `/runs/${need.item.run_id}` : '/workflows')
}

/**
 * What opens in the side panel (spec 3.5): a stop, a declined test run or a question opens its run, a request its approval, a
 * software that can't be found its row, and a connection that needs attention its state. Anything else follows its own first action, to its page.
 */
export function panelItemOf(need: Need): PanelItem | null {
  switch (need.kind) {
    case 'approval':
      return approvalItem(need.item.run_id)
    case 'stopped':
    case 'declined':
    case 'question':
      return runItem(need.item.run_id)
    case 'address':
      return { kind: 'software', id: need.item.software_id }
    case 'connection':
      return noModel(need.item) ? null : { kind: 'connection', id: need.item.id }
    case 'confirmation':
    case 'reply':
      return null
  }
}

export interface Pinned {
  readonly need: Need
  /** The rest of Needs you, so `more + 1` is the one number every place shows. */
  readonly more: number
}

/** The most urgent of the grouped needs, or null when nothing needs the person. */
export function pinnedOf(home: HomeOut): Pinned | null {
  const [need] = needsOf(home).shown
  return need === undefined ? null : { need, more: Math.max(0, needsTotal(home) - 1) }
}

/** On Home with no AI model the hero already offers Connect a model, so the model's row points to it instead of offering a second button. */
export const CONNECT_ABOVE = 'Connect one with the button above.'
export const NO_MODEL_TITLE = NO_MODEL.title
export const isModelNeed = (need: Need): boolean => need.kind === 'connection' && need.item.id === 'model'

export const CAN_RUN_AGAIN = 'Can run again once an AI model is connected.'
export const CAN_TEST_AGAIN = 'A test run can start again once an AI model is connected.'

/**
 * A declined test run opens the run, and lets its owner, an Operator, try the workflow again as a new test run. With no AI model
 * that run would stop at once, so only the reading stays, and the row says why.
 */
export function declinedActions(item: DeclinedItem, modelOff = false): readonly Action[] {
  const open: Action = { kind: 'open', label: 'See the run', to: `/runs/${item.run_id}`, item: runItem(item.run_id) }
  return modelOff ? [open] : [open, { kind: 'test', label: 'Do a test run again', useCaseId: item.use_case_id }]
}

/**
 * A stopped run offers Retry when the platform says it can be retried, and always a way to read why it stopped.
 * With no AI model a retry would fail again, so the run waits and only the reading stays (spec 5.4).
 */
export function stoppedActions(runId: string, retryable: boolean, modelOff = false): readonly Action[] {
  const item = runItem(runId)
  if (retryable && modelOff) return [{ kind: 'open', label: 'See the run', to: `/runs/${runId}`, item }]
  return retryable
    ? [
        { kind: 'retry', label: 'Retry the run', runId },
        { kind: 'open', label: 'See the run', to: `/runs/${runId}`, item },
      ]
    : [{ kind: 'open', label: 'See why it stopped', to: `/runs/${runId}`, item }]
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

/** The four steps of the removed New workflow screen, which a draft saved by it still counts in. */
const OLD_DRAFT_STEPS = 4

/** `left` is what setupLeft says of the saved card, or null when the draft holds no card (an old four-step draft, or only words). */
export function draftWords(draft: DraftItem, now: Date, left?: Left | null): RowWords {
  const saved = `Last saved ${runWhen(draft.saved_at, now)}.`
  const why =
    left === undefined
      ? draft.step === null
        ? ''
        : `Step ${draft.step} of ${OLD_DRAFT_STEPS}. `
      : left === null
        ? 'Only your words are saved. '
        : left.choices.length > 0
          ? `Needs ${andList(left.choices)}. `
          : left.leftOut.length > 0
            ? `${crossedWords(left.leftOut.length)} `
            : 'Nothing is unclear. '
  return { name: draft.name ?? 'New workflow', sub: `${why}${saved}` }
}

