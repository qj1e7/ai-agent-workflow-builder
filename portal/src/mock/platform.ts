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
  TeamsStubMessage,
  UseCaseView,
  Verdict,
  WatchlistView,
  WriteActionView,
} from '../api/types'
import { DemoCards } from './cards'
import { fixtures } from './fixtures'
import { json, problem } from './http'
import { CARD_RUN, FIRST_NEW_TICKET_NUMBER, RELEASE_CHECK, WATCHLIST_CHECK, type Person, type RunContext } from './recordings'
import { Run } from './run'
import type { ApprovalRecord } from './runView'
import { finished, replay, Timeline } from './timeline'
import { DemoModelSettings } from './settings'
import { DemoWatchlist, type CheckEvents } from './watchlist'

const HOUR_MS = 3_600_000
const SEEDED_FAILURE_AGE_MS = 3 * HOUR_MS
const SEEDED_REJECTED_AGE_MS = 26 * HOUR_MS
const SEEDED_USE_CASE_AGE_MS = 48 * HOUR_MS

export type DecideResult =
  | { kind: 'not_found' }
  | { kind: 'refused'; refusal: Refusal; message: string }
  | { kind: 'conflict' }
  | { kind: 'recorded'; created: boolean; out: DecisionOut }

export type RetryResult = { kind: 'not_found' } | { kind: 'not_retryable' } | { kind: 'accepted' }

export type StartResult =
  { kind: 'started'; run: Run } | { kind: 'not_found' } | { kind: 'nothing_to_check' } | { kind: 'needs_model' }

const TITLES_SHOWN = 5
const OPERATORS_ONLY = 'Only an Operator can do this. Ask an Operator on the team.'

function listed(items: readonly string[]): string {
  return items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1) ?? ''}`
}

function textOf(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

/** What a proposal would write, as the platform's Teams stub words it: tickets for one project become one phrase. */
export function wouldDo(actions: readonly WriteActionView[]): string {
  const phrases: string[] = []
  const titles = new Map<string, { slot: number; titles: string[] }>()
  for (const action of actions) {
    const title = textOf(action.fields['title'], '').replaceAll('"', '')
    if (action.connector !== 'jira' || action.operation !== 'create_ticket') {
      phrases.push(`${action.operation} on ${action.connector}`)
      continue
    }
    const project = textOf(action.target['project'], '?')
    const group = titles.get(project) ?? { slot: phrases.push('') - 1, titles: [] }
    group.titles.push(title)
    titles.set(project, group)
  }
  for (const [project, group] of titles) {
    const [only] = group.titles
    if (group.titles.length === 1 && only !== undefined) {
      phrases[group.slot] = `create a Jira ticket in ${project} titled "${only}"`
      continue
    }
    const quoted = group.titles.slice(0, TITLES_SHOWN).map((title) => `"${title}"`)
    const more = group.titles.length - quoted.length
    const shown = more === 0 ? listed(quoted) : `${quoted.join(', ')} and ${more} more`
    phrases[group.slot] = `create ${group.titles.length} Jira tickets in ${project}: ${shown}`
  }
  return listed(phrases)
}

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
  readonly watchlist: DemoWatchlist
  readonly cards: DemoCards
  private readonly runs: Run[]
  private readonly done = new Map<string, string>()
  private readonly useCases: UseCaseView[]
  private readonly startedRuns = new Map<string, string>()
  private counter = 0
  private nextTicket = FIRST_NEW_TICKET_NUMBER

  constructor(start: number) {
    this.useCases = [
      { ...fixtures.useCase, created_at: new Date(start - SEEDED_USE_CASE_AGE_MS).toISOString() },
    ]
    this.runs = [this.seedLive(start), this.seedFinished('failure', start), this.seedFinished('rejected', start)]
    this.watchlist = new DemoWatchlist(start)
    this.cards = new DemoCards(start)
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
    const watchlist = this.watchlist.useCase()
    const all = watchlist ? [watchlist, ...this.useCases] : [...this.useCases]
    return all.reverse().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
  }

  useCase(useCaseId: string): UseCaseView | undefined {
    const watchlist = this.watchlist.useCase()
    if (watchlist?.use_case_id === useCaseId) return watchlist
    return this.useCases.find((candidate) => candidate.use_case_id === useCaseId)
  }

  /** The watchlist's checks so far, oldest first, as the watchlist reads them. */
  watchlistChecks(wall: number): CheckEvents[] {
    return this.runs
      .filter((run) => run.meta.useCaseId === this.watchlist.useCaseId)
      .map((run) => {
        const view = run.view(wall)
        return { runId: run.id, state: view.state, startedAt: view.started_at, events: run.timeline.emitted(wall) }
      })
      .sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt))
  }

  watchlistView(wall: number): WatchlistView | null {
    return this.watchlist.view(this.watchlistChecks(wall), this.done, wall)
  }

  markDone(user: DevUser, key: string, wall: number): Response {
    if (!user.roles.includes('operator')) return problem(403, OPERATORS_ONLY)
    if (!this.jiraTickets(wall).some((ticket) => ticket.key === key)) return problem(404, 'There is no such ticket.')
    if (!this.done.has(key)) this.done.set(key, new Date(wall).toISOString())
    const ticket = this.jiraTickets(wall).find((candidate) => candidate.key === key)
    return json(200, ticket)
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
      plan: fixtures.templates.find((template) => template.key === input.template)?.blocks ?? [],
      agents: [],
    }
    this.useCases.push(created)
    return created
  }

  createAgentUseCase(owner: DevUser, body: unknown, wall: number): Response {
    const made = this.cards.agentUseCase(body, owner, this.newId('uc'), wall)
    if (made.kind === 'refused') return made.response
    this.useCases.push(made.useCase)
    return json(201, { use_case_id: made.useCase.use_case_id, version: made.useCase.version })
  }

  startRun(starter: DevUser, useCaseId: string, idempotencyKey: string, wall: number): StartResult {
    const useCase = this.useCase(useCaseId)
    if (!useCase) return { kind: 'not_found' }
    const remembered = this.startedRuns.get(`${starter.id}:${idempotencyKey}`)
    const existing = remembered ? this.run(remembered) : undefined
    if (existing) return { kind: 'started', run: existing }
    const check = useCase.template === 'software_watchlist'
    if (check && this.watchlist.isEmpty) return { kind: 'nothing_to_check' }
    const cards = useCase.template === 'agent_cards'
    if (cards && this.modelSettings.view(starter).active === null) return { kind: 'needs_model' }
    const recording = check ? WATCHLIST_CHECK : cards ? CARD_RUN : RELEASE_CHECK
    const first = useCase.agents[0]
    const cardView = first ? this.cards.get(first.card_id) : undefined
    const valueOfKind = (kind: string) => {
      const input = cardView?.inputs.find((each) => each.kind === kind)
      return input ? first?.values[input.name] : undefined
    }

    const context: RunContext = {
      runId: this.newId('run'),
      starter: person(starter),
      useCase: { id: useCase.use_case_id, name: useCase.name },
      repo: cards ? valueOfKind('github_repo') : useCase.params['repo'],
      ...(first && cards ? { card: { id: first.card_id, name: first.name, project: valueOfKind('jira_project') ?? 'MOCK' } } : {}),
      approvalId: this.newId('apr'),
      proposalId: this.newId('prp'),
    }
    const timeline = new Timeline(replay(recording.workLeg(context, { firstSeq: 1, attempt: 1 }), { wall, recorded: wall }))
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
      [recording.proposalFor(context)],
      recording,
    )
    this.runs.push(run)
    this.startedRuns.set(`${starter.id}:${idempotencyKey}`, run.id)
    return { kind: 'started', run }
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
          if (!record || record.actions.length === 0) return []
          const message: TeamsStubMessage = {
            id: `tm_${record.approval_id.slice('apr_'.length)}`,
            ts: event.ts,
            channel: event.data.channel,
            text: `A run of ${run.meta.useCaseName} needs an Approver. It would ${wouldDo(record.actions)}. Open the approval page to decide.${agentsSaid(emitted)}`,
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
        // The writes after a decision come in the proposal's order, so the nth write is the nth action.
        let written = 0
        return run.timeline.emitted(wall).flatMap((event) => {
          if (event.kind === 'approval_decided') written = 0
          if (event.kind !== 'write_action_done' || !record) return []
          const action = record.actions[written]
          written += 1
          if (!action) return []
          const doneAt = this.done.get(event.data.external_reference) ?? null
          const ticket: MockJiraTicket = {
            key: event.data.external_reference,
            project: String(action.target['project']),
            title: String(action.fields['title']),
            body: String(action.fields['body']),
            created_at: event.ts,
            run_id: run.id,
            proposal_id: record.proposal_id,
            status: doneAt ? 'Done' : 'To Do',
            done_at: doneAt,
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
