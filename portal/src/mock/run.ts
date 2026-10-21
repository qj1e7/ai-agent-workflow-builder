import type { ProposalView, RunView, Verdict } from '../api/types'
import {
  decisionTail,
  proposalFor,
  retriedEvent,
  workLeg,
  type Person,
  type RunContext,
} from './recordings'
import { foldApprovals, foldView, type ApprovalRecord, type RunMeta } from './runView'
import { replay, type Timeline } from './timeline'

export const RETRY_DELAY_MS = 1500

export interface RetryIds {
  readonly approvalId: string
  readonly proposalId: string
}

export class Run {
  readonly meta: RunMeta
  readonly starter: Person
  readonly timeline: Timeline
  private readonly proposals: ProposalView[]
  private context: RunContext
  // The approval counts a real decision from the moment it is made, while the room still narrates what came before it.
  private decidedAt = -Infinity

  constructor(meta: RunMeta, context: RunContext, timeline: Timeline, proposals: readonly ProposalView[]) {
    this.meta = meta
    this.starter = context.starter
    this.context = context
    this.timeline = timeline
    this.proposals = [...proposals]
  }

  get id(): string {
    return this.meta.id
  }

  view(wall: number): RunView {
    return foldView(this.meta, this.timeline.emitted(wall), this.proposals)
  }

  approvals(wall: number): ApprovalRecord[] {
    return foldApprovals(this.id, this.timeline.emitted(Math.max(wall, this.decidedAt)), this.proposals)
  }

  proposalFor(proposalId: string): ProposalView | undefined {
    return this.proposals.find((proposal) => proposal.proposal_id === proposalId)
  }

  startedAt(): number {
    return Date.parse(this.view(Infinity).started_at)
  }

  /** A real decision replaces whatever the recording would have decided, and plays the rest of the run. */
  decide(verdict: Verdict, decider: Person, ticketKey: () => string, wall: number): void {
    const recorded = this.timeline.recordedAt(wall)
    this.timeline.discardPendingDecision(wall)
    const start = Math.max(wall, this.timeline.lastAt)
    this.decidedAt = start
    const key = verdict === 'approve' ? ticketKey() : 'MOCK-142'
    const tail = decisionTail(verdict, this.context, decider, key, this.timeline.lastSeq + 1)
    this.timeline.append(replay(tail, { wall: start, recorded: recorded + (start - wall) }))
  }

  retry(by: Person, ids: RetryIds, wall: number): void {
    const attempt = 2 + this.timeline.emitted(Infinity).filter((event) => event.kind === 'run_retried').length
    this.context = { ...this.context, ...ids }
    this.proposals.push(proposalFor(this.context))
    const recorded = this.timeline.recordedAt(wall)
    const retried = retriedEvent(this.context, by, attempt, this.timeline.lastSeq + 1)
    const work = workLeg(this.context, { firstSeq: retried.seq + 1, attempt })
    this.timeline.append([
      ...replay([retried], { wall, recorded }),
      ...replay(work, { wall: wall + RETRY_DELAY_MS, recorded: recorded + RETRY_DELAY_MS }),
    ])
  }
}
