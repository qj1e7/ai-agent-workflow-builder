import type {
  ActivityEvent,
  ApprovalView,
  CreateUseCase,
  DecisionOut,
  DecisionView,
  DevUser,
  EventOf,
  MockJiraTicket,
  ProposalView,
  Refusal,
  RunView,
  SuggestOut,
  TeamsStubMessage,
  UseCaseView,
  Verdict,
} from '../api/types'
import { fixtures } from './fixtures'
import { FIRST_NEW_TICKET_NUMBER, proposalFor, workLeg, type Person, type RunContext } from './recordings'
import { Run } from './run'
import type { ApprovalRecord } from './runView'
import { finished, replay, Timeline } from './timeline'
import { DemoModelSettings } from './settings'

const HOUR_MS = 3_600_000
const SEEDED_FAILURE_AGE_MS = 3 * HOUR_MS
const SEEDED_REJECTED_AGE_MS = 26 * HOUR_MS
const SEEDED_USE_CASE_AGE_MS = 48 * HOUR_MS
const MATCHED_TERMS = /\b(releases?|tickets?)\b/gi

export type DecideResult =
  | { kind: 'not_found' }
  | { kind: 'refused'; refusal: Refusal; message: string }
  | { kind: 'conflict' }
  | { kind: 'recorded'; created: boolean; out: DecisionOut }

export type RetryResult = { kind: 'not_found' } | { kind: 'not_retryable' } | { kind: 'accepted' }

interface FoundApproval {
  readonly run: Run
  readonly record: ApprovalRecord
}

function person(user: DevUser): Person {
  return { id: user.id, display: user.display }
}

// The agents' summary, labelled and last, the way the platform ends the Teams message.
function agentsSaid(events: readonly ActivityEvent[]): string {
  const said = events.findLast(
    (event): event is EventOf<'step_finished'> =>
      event.kind === 'step_finished' && event.data.step === 'run_agents' && event.data.outcome === 'proposed',
  )?.data.detail
  if (!said) return ''
  return ` The agents said: ${/[.!?…]$/.test(said) ? said : `${said}.`}`
}

export class DemoPlatform {
  readonly modelSettings = new DemoModelSettings()
  private readonly runs: Run[]
  private readonly useCases: UseCaseView[]
  private readonly startedRuns = new Map<string, string>()
  private counter = 0
  private nextTicket = FIRST_NEW_TICKET_NUMBER

  constructor(start: number) {
    this.useCases = [
      { ...fixtures.useCase, created_at: new Date(start - SEEDED_USE_CASE_AGE_MS).toISOString() },
    ]
    this.runs = [this.seedLive(start), this.seedFinished('failure', start), this.seedFinished('rejected', start)]
  }

  users(): DevUser[] {
    return fixtures.devUsers
  }

  user(id: string | null): DevUser | undefined {
    return fixtures.devUsers.find((candidate) => candidate.id === id)
  }

  clock(runId: string, wall: number): number {
    return this.run(runId)?.timeline.recordedAt(wall) ?? wall
  }

  clockRate(runId: string, wall: number): number {
    return this.run(runId)?.timeline.rateAt(wall) ?? 1
  }

  run(runId: string): Run | undefined {
    return this.runs.find((candidate) => candidate.id === runId)
  }

  listRuns(wall: number): RunView[] {
    return this.runs
      .map((run) => run.view(wall))
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
  }

  listUseCases(): UseCaseView[] {
    return [...this.useCases].reverse()
  }

  useCase(useCaseId: string): UseCaseView | undefined {
    return this.useCases.find((candidate) => candidate.use_case_id === useCaseId)
  }

  suggest(text: string): SuggestOut {
    const found = [...text.matchAll(MATCHED_TERMS)].map((match) => (match[1] ?? '').toLowerCase())
    const matchedTerms = [...new Set(found)]
    return { template: matchedTerms.length > 0 ? fixtures.releaseCheck : null, matched_terms: matchedTerms }
  }

  createUseCase(owner: DevUser, input: CreateUseCase, wall: number): UseCaseView {
    const created: UseCaseView = {
      use_case_id: this.newId('uc'),
      version: 1,
      template: input.template,
      name: input.name,
      instruction: input.instruction,
      params: input.params,
      owner: owner.id,
      created_at: new Date(wall).toISOString(),
    }
    this.useCases.push(created)
    return created
  }

  startRun(starter: DevUser, useCaseId: string, idempotencyKey: string, wall: number): Run | undefined {
    const useCase = this.useCase(useCaseId)
    if (!useCase) return undefined
    const remembered = this.startedRuns.get(`${starter.id}:${idempotencyKey}`)
    const existing = remembered ? this.run(remembered) : undefined
    if (existing) return existing

    const context: RunContext = {
      runId: this.newId('run'),
      starter: person(starter),
      useCase: { id: useCase.use_case_id, name: useCase.name },
      repo: useCase.params['repo'],
      approvalId: this.newId('apr'),
      proposalId: this.newId('prp'),
    }
    const timeline = new Timeline(replay(workLeg(context, { firstSeq: 1, attempt: 1 }), { wall, recorded: wall }))
    const run = new Run(
      {
        id: context.runId,
        useCaseId: useCase.use_case_id,
        useCaseName: useCase.name,
        useCaseVersion: useCase.version,
        startedBy: starter.id,
      },
      context,
      timeline,
      [proposalFor(context)],
    )
    this.runs.push(run)
    this.startedRuns.set(`${starter.id}:${idempotencyKey}`, run.id)
    return run
  }

  retry(by: DevUser, runId: string, wall: number): RetryResult {
    const run = this.run(runId)
    if (!run) return { kind: 'not_found' }
    const view = run.view(wall)
    if (view.state !== 'failed' || !view.retryable) return { kind: 'not_retryable' }
    run.retry(person(by), { approvalId: this.newId('apr'), proposalId: this.newId('prp') }, wall)
    return { kind: 'accepted' }
  }

  approval(approvalId: string, caller: DevUser, wall: number): ApprovalView | undefined {
    const found = this.findApproval(approvalId, wall)
    if (!found) return undefined
    const refusal = this.refusalFor(caller, found)
    const { record } = found
    return {
      approval_id: record.approval_id,
      run_id: record.run_id,
      digest: record.digest,
      actions: record.actions,
      steps: record.steps,
      you_can_decide: refusal === null,
      why_not: refusal,
    }
  }

  decide(caller: DevUser, approvalId: string, step: number, verdict: Verdict, digest: string, wall: number): DecideResult {
    const found = this.findApproval(approvalId, wall)
    if (!found) return { kind: 'not_found' }
    const { run, record } = found

    const refusal = this.roleRefusal(caller, run)
    if (refusal) return this.refused(refusal)

    const target = record.steps.find((candidate) => candidate.index === step)
    if (!target) return this.refused('wrong_step')
    if (target.status === 'approved' || target.status === 'declined') {
      const sameVerdict = (target.status === 'approved') === (verdict === 'approve')
      if (!sameVerdict) return { kind: 'conflict' }
      return { kind: 'recorded', created: false, out: this.outcomeOf(approvalId, step, wall) }
    }
    if (target.status !== 'open') return this.refused('wrong_step')
    if (digest !== record.digest) return this.refused('stale_digest')

    run.decide(verdict, person(caller), () => this.newTicketKey(), wall)
    return { kind: 'recorded', created: true, out: this.outcomeOf(approvalId, step, wall) }
  }

  teamsMessages(wall: number): TeamsStubMessage[] {
    return this.runs
      .flatMap((run) => {
        const records = run.approvals(wall)
        const emitted = run.timeline.emitted(wall)
        return emitted.flatMap((event) => {
          if (event.kind !== 'approval_announced') return []
          const record = records.find((candidate) => candidate.approval_id === event.data.approval_id)
          const action = record?.actions[0]
          if (!record || !action) return []
          const message: TeamsStubMessage = {
            id: `tm_${record.approval_id.slice('apr_'.length)}`,
            ts: event.ts,
            channel: event.data.channel,
            text: `A run of ${run.meta.useCaseName} needs an Approver. It would create a Jira ticket in ${String(action.target['project'])} titled "${String(action.fields['title'])}". Open the approval page to decide.${agentsSaid(emitted)}`,
            link: event.data.link,
            run_id: run.id,
            approval_id: record.approval_id,
          }
          return [message]
        })
      })
      .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
  }

  jiraTickets(wall: number): MockJiraTicket[] {
    return this.runs
      .flatMap((run) => {
        const record = run.approvals(wall).at(-1)
        const action = record?.actions[0]
        return run.timeline.emitted(wall).flatMap((event) => {
          if (event.kind !== 'write_action_done' || !record || !action) return []
          const ticket: MockJiraTicket = {
            key: event.data.external_reference,
            project: String(action.target['project']),
            title: String(action.fields['title']),
            body: String(action.fields['body']),
            created_at: event.ts,
            run_id: run.id,
            proposal_id: record.proposal_id,
            status: 'To Do',
            done_at: null,
          }
          return [ticket]
        })
      })
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }

  private seedLive(start: number): Run {
    const timeline = new Timeline(replay(fixtures.successEvents, { wall: start, recorded: start }))
    return this.seeded('run_01JB8', 'prp_01JB8', 'apr_01JB8', timeline, [fixtures.successProposal])
  }

  private seedFinished(which: 'failure' | 'rejected', start: number): Run {
    const failure = which === 'failure'
    const events = failure ? fixtures.failureEvents : fixtures.rejectedEvents
    const timeline = new Timeline(finished(events, start - (failure ? SEEDED_FAILURE_AGE_MS : SEEDED_REJECTED_AGE_MS)))
    return failure
      ? this.seeded('run_01JB9', this.newId('prp'), this.newId('apr'), timeline, [])
      : this.seeded('run_01JBA', 'prp_01JBA', 'apr_01JBA', timeline, [fixtures.rejectedProposal])
  }

  private seeded(
    runId: string,
    proposalId: string,
    approvalId: string,
    timeline: Timeline,
    proposals: readonly ProposalView[],
  ): Run {
    const { use_case_id: useCaseId, name, version } = fixtures.useCase
    const context: RunContext = {
      runId,
      starter: { id: 'alice', display: 'Alice' },
      useCase: { id: useCaseId, name },
      repo: undefined,
      approvalId,
      proposalId,
    }
    return new Run(
      { id: runId, useCaseId, useCaseName: name, useCaseVersion: version, startedBy: 'alice' },
      context,
      timeline,
      proposals,
    )
  }

  private findApproval(approvalId: string, wall: number): FoundApproval | undefined {
    for (const run of this.runs) {
      const record = run.approvals(wall).find((candidate) => candidate.approval_id === approvalId)
      if (record) return { run, record }
    }
    return undefined
  }

  private roleRefusal(caller: DevUser, run: Run): Refusal | null {
    if (!caller.roles.includes('approver')) return 'not_an_approver'
    return caller.id === run.starter.id ? 'own_work' : null
  }

  private refusalFor(caller: DevUser, { run, record }: FoundApproval): Refusal | null {
    return this.roleRefusal(caller, run) ?? (record.steps.some((step) => step.status === 'open') ? null : 'not_open')
  }

  private refused(refusal: Refusal): DecideResult {
    return { kind: 'refused', refusal, message: REFUSAL_MESSAGES[refusal] }
  }

  private outcomeOf(approvalId: string, step: number, wall: number): DecisionOut {
    const found = this.findApproval(approvalId, wall)
    const steps = found?.record.steps ?? []
    const decided = steps.find((candidate) => candidate.index === step)
    const decision: DecisionView = {
      step,
      by: decided?.decided_by ?? '',
      verdict: decided?.status === 'declined' ? 'decline' : 'approve',
      at: decided?.decided_at ?? new Date(wall).toISOString(),
    }
    const status = steps.some((candidate) => candidate.status === 'declined')
      ? 'declined'
      : steps.every((candidate) => candidate.status === 'approved')
        ? 'approved'
        : 'open'
    return { status, decision }
  }

  private newId(prefix: string): string {
    this.counter += 1
    return `${prefix}_demo${this.counter}`
  }

  private newTicketKey(): string {
    const key = `MOCK-${this.nextTicket}`
    this.nextTicket += 1
    return key
  }
}

const REFUSAL_MESSAGES: Record<Refusal, string> = {
  own_work: fixtures.ownWorkRefusal.message,
  not_an_approver: 'Only Approvers can decide this request.',
  not_eligible: 'You are not one of the Approvers for this step.',
  decided_earlier_step: 'You already decided an earlier step.',
  wrong_step: 'This is not the step that is waiting for a decision.',
  not_open: 'This request is not open for a decision.',
  stale_digest: 'The request changed after you opened this page.',
  invalid_decisions: 'This approval has a problem.',
}
