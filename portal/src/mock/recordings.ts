import type { ActivityEvent, ProposalView, Verdict } from '../api/types'
import { fixtures } from './fixtures'
import { substitute, type Replacement } from './substitute'

export interface Person {
  readonly id: string
  readonly display: string
}

export interface RunContext {
  readonly runId: string
  readonly starter: Person
  readonly useCase: { readonly id: string; readonly name: string }
  readonly repo: string | undefined
  readonly approvalId: string
  readonly proposalId: string
}

interface WorkLegOptions {
  readonly firstSeq: number
  readonly attempt: number
}

/** One recorded run the demo replays for a run it starts: the work leg, the rest after a decision, and the proposal. */
export interface Recording {
  readonly workLeg: (context: RunContext, options: WorkLegOptions) => ActivityEvent[]
  /** keys are the ticket keys an approval writes, one for each of `tickets`. */
  readonly decisionTail: (
    verdict: Verdict,
    context: RunContext,
    decider: Person,
    keys: readonly string[],
    firstSeq: number,
  ) => ActivityEvent[]
  readonly proposalFor: (context: RunContext) => ProposalView
  readonly tickets: number
}

const RECORDED_DECIDER: Person = { id: 'bob', display: 'Bob' }
export const FIRST_NEW_TICKET_NUMBER = 143

function numbered(events: readonly ActivityEvent[], firstSeq: number): ActivityEvent[] {
  return events.map((event, index) => ({ ...event, seq: firstSeq + index }))
}

function withAttempt(event: ActivityEvent, attempt: number): ActivityEvent {
  if (event.kind !== 'leg_dispatched') return event
  return {
    ...event,
    summary: event.summary.replace('(attempt 1)', `(attempt ${attempt})`),
    data: { ...event.data, attempt },
  }
}

function lastSeqOfWorkLeg(events: readonly ActivityEvent[]): number {
  return events.find((event) => event.kind === 'approval_announced')?.seq ?? events.length
}

function playWorkLeg(
  recorded: readonly ActivityEvent[],
  replacements: readonly Replacement[],
  { firstSeq, attempt }: WorkLegOptions,
): ActivityEvent[] {
  const events = firstSeq === 1 ? recorded : recorded.slice(1)
  return numbered(
    substitute(events, replacements).map((event) => withAttempt(event, attempt)),
    firstSeq,
  )
}

// The release check: runs/success.json, with runs/rejected.json for a decline.
const RELEASE_LAST = lastSeqOfWorkLeg(fixtures.successEvents)
const releaseWorkLeg = fixtures.successEvents.filter((event) => event.seq <= RELEASE_LAST)
const releaseActLeg = fixtures.successEvents.filter((event) => event.seq > RELEASE_LAST)
const releaseDecline = fixtures.rejectedEvents.filter((event) => event.seq > lastSeqOfWorkLeg(fixtures.rejectedEvents))

function releaseReplacements(context: RunContext, decider: Person, ticketKey: string): Replacement[] {
  const [useCaseName, repo] = [context.useCase.name, context.repo ?? 'langchain-ai/langgraph']
  return [
    ['run_01JB8', context.runId],
    ['run_01JBA', context.runId],
    ['apr_01JB8', context.approvalId],
    ['apr_01JBA', context.approvalId],
    ['prp_01JB8', context.proposalId],
    ['prp_01JBA', context.proposalId],
    ['uc_01JB7', context.useCase.id],
    ['a run of LangGraph releases', `a run of ${useCaseName}`],
    ['langchain-ai/langgraph', repo],
    ['Alice', context.starter.display],
    ['alice', context.starter.id],
    ['Bob', decider.display],
    ['bob', decider.id],
    ['MOCK-142', ticketKey],
  ]
}

function declineTail(context: RunContext, decider: Person, firstSeq: number): ActivityEvent[] {
  return numbered(substitute(releaseDecline, releaseReplacements(context, decider, 'MOCK-142')), firstSeq)
}

export const RELEASE_CHECK: Recording = {
  workLeg: (context, options) =>
    playWorkLeg(releaseWorkLeg, releaseReplacements(context, RECORDED_DECIDER, 'MOCK-142'), options),
  decisionTail: (verdict, context, decider, keys, firstSeq) =>
    verdict === 'approve'
      ? numbered(substitute(releaseActLeg, releaseReplacements(context, decider, keys[0] ?? 'MOCK-142')), firstSeq)
      : declineTail(context, decider, firstSeq),
  proposalFor: (context) =>
    substitute(fixtures.successProposal, releaseReplacements(context, RECORDED_DECIDER, 'MOCK-142')),
  tickets: 1,
}

// The watchlist check: runs/watchlist.json, which writes one ticket for each software that is behind.
const WATCH_LAST = lastSeqOfWorkLeg(fixtures.watchlistEvents)
const watchWorkLeg = fixtures.watchlistEvents.filter((event) => event.seq <= WATCH_LAST)
const watchActLeg = fixtures.watchlistEvents.filter((event) => event.seq > WATCH_LAST)
const watchKeys = [
  ...new Set(
    watchActLeg.flatMap((event) => (event.kind === 'write_action_done' ? [event.data.external_reference] : [])),
  ),
]

function watchReplacements(context: RunContext, decider: Person, keys: readonly string[]): Replacement[] {
  const [first] = fixtures.watchlistEvents
  const runId = first?.run_id ?? ''
  const suffix = runId.slice('run_'.length)
  const useCaseId = first?.kind === 'run_created' ? first.data.use_case_id : ''
  return [
    [runId, context.runId],
    [`apr_${suffix}`, context.approvalId],
    [`prp_${suffix}`, context.proposalId],
    [useCaseId, context.useCase.id],
    ['Alice', context.starter.display],
    ['alice', context.starter.id],
    ['Bob', decider.display],
    ['bob', decider.id],
    ...watchKeys.map((key, index): Replacement => [key, keys[index] ?? key]),
  ]
}

export const WATCHLIST_CHECK: Recording = {
  workLeg: (context, options) =>
    playWorkLeg(watchWorkLeg, watchReplacements(context, RECORDED_DECIDER, watchKeys), options),
  decisionTail: (verdict, context, decider, keys, firstSeq) =>
    verdict === 'approve'
      ? numbered(substitute(watchActLeg, watchReplacements(context, decider, keys)), firstSeq)
      : declineTail(context, decider, firstSeq),
  proposalFor: (context) =>
    substitute(fixtures.watchlistProposal, watchReplacements(context, RECORDED_DECIDER, watchKeys)),
  tickets: watchKeys.length,
}

export function retriedEvent(context: RunContext, by: Person, attempt: number, seq: number): ActivityEvent {
  return {
    run_id: context.runId,
    seq,
    ts: new Date(0).toISOString(),
    actor: { kind: 'user', id: by.id, display: by.display },
    kind: 'run_retried',
    summary: `${by.display} retried the run.`,
    data: { leg: 'work', attempt },
  }
}
