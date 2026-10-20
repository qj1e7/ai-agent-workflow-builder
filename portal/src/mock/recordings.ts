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

const WORK_LEG_LAST_SEQ = 17
const RECORDED_DECIDER: Person = { id: 'bob', display: 'Bob' }
export const FIRST_NEW_TICKET_NUMBER = 143

const recordedWorkLeg = fixtures.successEvents.filter((event) => event.seq <= WORK_LEG_LAST_SEQ)
const recordedActLeg = fixtures.successEvents.filter((event) => event.seq > WORK_LEG_LAST_SEQ)
const recordedDecline = fixtures.rejectedEvents.filter((event) => event.seq > WORK_LEG_LAST_SEQ)

function replacements(context: RunContext, decider: Person, ticketKey: string): Replacement[] {
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

interface WorkLegOptions {
  readonly firstSeq: number
  readonly attempt: number
}

export function workLeg(context: RunContext, { firstSeq, attempt }: WorkLegOptions): ActivityEvent[] {
  const events = firstSeq === 1 ? recordedWorkLeg : recordedWorkLeg.slice(1)
  const own = substitute(events, replacements(context, RECORDED_DECIDER, 'MOCK-142'))
  return numbered(own.map((event) => withAttempt(event, attempt)), firstSeq)
}

export function decisionTail(
  verdict: Verdict,
  context: RunContext,
  decider: Person,
  ticketKey: string,
  firstSeq: number,
): ActivityEvent[] {
  const recorded = verdict === 'approve' ? recordedActLeg : recordedDecline
  return numbered(substitute(recorded, replacements(context, decider, ticketKey)), firstSeq)
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

export function proposalFor(context: RunContext): ProposalView {
  return substitute(fixtures.successProposal, replacements(context, RECORDED_DECIDER, 'MOCK-142'))
}

export function recordedContext(runId: string, proposalId: string, approvalId: string): RunContext {
  return {
    runId,
    starter: { id: 'alice', display: 'Alice' },
    useCase: { id: fixtures.useCase.use_case_id, name: fixtures.useCase.name },
    repo: undefined,
    approvalId,
    proposalId,
  }
}
