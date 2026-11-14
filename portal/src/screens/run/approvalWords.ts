import { connectorLabel } from '../../api/labels'
import type { ApprovalActionView, ApprovalView, Refusal, WriteActionView } from '../../api/types'
import type { Standing } from './decision'
import { andList, count, sentence, settledWhen, stageWords, type NameOf, type StageFacts, type StageTone } from './words'

const isTicket = (action: Pick<WriteActionView, 'connector' | 'operation'>) => action.connector === 'jira' && action.operation === 'create_ticket'

/** "Create 1 Jira ticket", or what else the request writes and where: the head of the card, the panel and the page. */
export function approvalTitle(actions: readonly Pick<WriteActionView, 'connector' | 'operation'>[]): string {
  if (actions.length > 0 && actions.every(isTicket)) return `Create ${count(actions.length, 'Jira ticket')}`
  const where = new Set(actions.map((action) => connectorLabel(action.connector)))
  return `Write ${count(actions.length, 'change')}${where.size === 1 ? ` in ${[...where].join('')}` : ''}`
}

/** "Approval, from Alice’s FastAPI release check": whose workflow asks. */
export function kindWords(approval: Pick<ApprovalView, 'owner' | 'use_case_name'>, nameOf: NameOf): string {
  return `Approval, from ${nameOf(approval.owner)}’s ${approval.use_case_name}`
}

/** "Jira project MOCK on the practice Jira": where one write goes, naming the Jira before the yes (ADR 0041). */
export function whereWords(action: ApprovalActionView): string {
  const project = action.target['project']
  const what = typeof project === 'string' ? `${connectorLabel(action.connector)} project ${project}` : connectorLabel(action.connector)
  return action.site_name ? `${what} on ${action.site_name}` : what
}

export interface Pill {
  readonly label: string
  readonly tone: StageTone
}

/** The request's one pill. While it waits, the person who may say yes reads that it needs theirs. */
export function approvalPill(standing: Standing, canDecide: boolean): Pill {
  switch (standing.is) {
    case 'open':
      return canDecide ? { label: 'Needs your yes', tone: 'wait' } : { label: 'Waiting for a yes', tone: 'wait' }
    case 'approved':
      return { label: 'Approved', tone: 'ok' }
    case 'declined':
      return { label: 'Declined', tone: 'quiet' }
    case 'expired':
      return { label: 'No answer', tone: 'quiet' }
    case 'cancelled':
      return { label: 'Cancelled', tone: 'quiet' }
  }
}

/** A rule with two Approvers says whose turn it is: "Step 1 of 2…", then "Step 2 of 2. Carol said yes first.". Null for one. */
export function turnWords(standing: Standing, nameOf: NameOf): string | null {
  if (standing.is !== 'open' || standing.steps < 2) return null
  const at = `Step ${String(standing.step + 1)} of ${String(standing.steps)}.`
  if (standing.step === 0) return `${at} It needs two Approvers, one after the other.`
  return standing.approvedBy.length > 0 ? `${at} ${andList(standing.approvedBy.map(nameOf))} said yes first.` : at
}

/** Why this person may say yes, and which of two yeses is theirs. */
export function whyYouWords(standing: Standing, nameOf: NameOf): string {
  if (standing.is === 'open' && standing.steps > 1 && standing.step > 0 && standing.approvedBy.length > 0) {
    return `${andList(standing.approvedBy.map(nameOf))} said yes. Your yes is the second of two.`
  }
  const own = 'No one can approve their own work.'
  return standing.is === 'open' && standing.steps > 1 ? `${own} Your yes is the first of two.` : own
}

/** Where the buttons would be, for someone who can't say yes: who it waits for, and why not them. */
export function waitingWords(whyNot: Refusal | null): string {
  switch (whyNot) {
    case 'own_work':
      return 'Waiting for an Approver. You can’t approve your own work.'
    case 'decided_earlier_step':
      return 'Waiting for another Approver. You said yes to the step before, and no one says yes twice.'
    case 'not_an_approver':
      return 'Waiting for an Approver. Only an Approver can decide.'
    case 'not_eligible':
      return 'Waiting for an Approver. You aren’t one of the people who can decide this step.'
    default:
      return 'Waiting for an Approver.'
  }
}

/** The line over the cards when someone asks what waits for their yes. */
export function leadWords(requests: number): string {
  return requests === 1 ? 'This needs your yes.' : 'These need your yes.'
}

const WRITING = new Set<StageFacts['state']>(['pending', 'working', 'proposed', 'awaiting_approval', 'acting'])

/** What the run did after the last yes, in the words every place gives a run's stage, without naming the Approvers again. */
function afterYes(facts: StageFacts, nameOf: NameOf): string {
  if (WRITING.has(facts.state)) return `${stageWords({ ...facts, state: 'acting' }, nameOf)}…`
  if (facts.state === 'lost') return 'n8n lost the run. Nothing was written.'
  return sentence(stageWords({ ...facts, approvedBy: [] }, nameOf))
}

const quickOrTyped = (reason: string, quick: readonly string[]) => sentence(quick.includes(reason) ? reason.charAt(0).toLowerCase() + reason.slice(1) : reason)

/**
 * The record once the request is decided or over: "Approved by Bob at 9:04. MOCK-22 created.", or "Declined by Bob at 9:04:
 * not this week. Nothing was written.". A declined record never names a result. Null while it waits.
 */
export function recordWords(standing: Standing, facts: StageFacts | null, nameOf: NameOf, quick: readonly string[], now: Date): string | null {
  const when = (at: string | null) => (at ? ` ${settledWhen(Date.parse(at), now)}` : '')
  switch (standing.is) {
    case 'open':
      return null
    case 'approved': {
      const head = `Approved by ${standing.by.map(nameOf).join(', then ')}${when(standing.at)}.`
      return facts ? `${head} ${afterYes(facts, nameOf)}` : head
    }
    case 'declined': {
      const { by, approvedBy, reason } = standing.record
      const who = approvedBy.length > 0 ? `Approved by ${approvedBy.map(nameOf).join(', then ')}, then declined by ${nameOf(by)}` : `Declined by ${nameOf(by)}`
      return `${who}${when(standing.at)}${reason ? `: ${quickOrTyped(reason, quick)}` : '.'} Nothing was written.`
    }
    case 'expired':
      return 'No one said yes in time. Nothing was written, and it can’t be decided now.'
    case 'cancelled':
      return 'The workflow was deleted before anyone decided. Nothing was written, and it can’t be decided now.'
  }
}

/** The short record at the left of the card's foot: "Approved. MOCK-22 created." or "Declined. Nothing was written.". */
export function cardStatusWords(standing: Standing, facts: StageFacts | null): string | null {
  switch (standing.is) {
    case 'open':
      return null
    case 'approved':
      return facts?.state === 'succeeded' && facts.count > 0 ? `Approved. ${sentence(stageWords({ ...facts, approvedBy: [] }, (id) => id))}` : 'Approved.'
    case 'declined':
      return 'Declined. Nothing was written.'
    case 'expired':
      return 'No answer. Nothing was written.'
    case 'cancelled':
      return 'Cancelled. Nothing was written.'
  }
}
