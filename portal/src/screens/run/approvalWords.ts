import { connectorLabel } from '../../api/labels'
import type { ApprovalActionView, ApprovalView, Refusal, WriteActionView } from '../../api/types'
import type { Standing } from './decision'
import { andList, count, LOST_TAIL, sentence, settledWhen, stageWords, type NameOf, type StageFacts, type StageTone } from './words'

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

/** A field's value as the write will carry it, in words. */
function valueWords(value: unknown): string {
  if (value === null || value === undefined) return 'None'
  if (typeof value === 'string') return value.trim() === '' ? 'Empty' : value
  if (Array.isArray(value)) return value.length === 0 ? 'None' : value.map(valueWords).join(', ')
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

const FIRST: Readonly<Record<string, string>> = { title: 'Summary', body: 'Details' }

export interface FieldRow {
  readonly key: string
  readonly label: string
  readonly value: string
}

/** Every field one write carries, as a row: Summary and Details first, then each other field under its own name. None is left out. */
export function fieldRows(fields: Readonly<Record<string, unknown>>): readonly FieldRow[] {
  const keys = [...Object.keys(FIRST).filter((key) => key in fields), ...Object.keys(fields).filter((key) => !(key in FIRST))]
  return keys.map((key) => {
    const words = key.replace(/[_-]+/g, ' ').trim()
    return { key, label: FIRST[key] ?? words.charAt(0).toUpperCase() + words.slice(1), value: valueWords(fields[key]) }
  })
}

export interface Pill {
  readonly label: string
  readonly tone: StageTone
}

/** What the person who may say yes reads in the pill, on the request and on its run's page. */
export const YOUR_YES: Pill = { label: 'Needs your yes', tone: 'wait' }

/** The request's one pill. While it waits, the person who may say yes reads that it needs theirs. */
export function approvalPill(standing: Standing, canDecide: boolean): Pill {
  switch (standing.is) {
    case 'open':
      return canDecide ? YOUR_YES : { label: 'Waiting for a yes', tone: 'wait' }
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

/** Why this person may say yes, and which of two yeses is theirs. Who said yes first is in the turn line, so it isn't said again. */
export function whyYouWords(standing: Standing): string {
  const own = 'No one can approve their own work.'
  if (standing.is !== 'open' || standing.steps < 2) return own
  return `${own} Your yes is the ${standing.step === 0 ? 'first' : 'second'} of two.`
}

const WHY_NOT: Partial<Record<Refusal, string>> = {
  own_work: 'You can’t approve your own work.',
  decided_earlier_step: 'You said yes to the step before, and no one says yes twice.',
  not_an_approver: 'Only an Approver can decide.',
  not_eligible: 'You aren’t one of the people who can decide this step.',
}

/**
 * Where the buttons would be, for someone who can't say yes: who it waits for, and why not them. `withWhy` is false where the page
 * already says why in its own row, so the reason is said once.
 */
export function waitingWords(whyNot: Refusal | null, withWhy = true): string {
  const who = whyNot === 'decided_earlier_step' ? 'Waiting for another Approver.' : 'Waiting for an Approver.'
  const why = whyNot ? WHY_NOT[whyNot] : undefined
  return withWhy && why ? `${who} ${why}` : who
}

/** The line over the cards: whose yes the requests need. Someone whose own run waits reads that it waits for an Approver. */
export function leadWords(requests: number, yours: boolean): string {
  if (yours) return requests === 1 ? 'This needs your yes.' : 'These need your yes.'
  return requests === 1 ? 'This waits for an Approver’s yes.' : 'These wait for an Approver’s yes.'
}

const WRITING = new Set<StageFacts['state']>(['pending', 'working', 'proposed', 'awaiting_approval', 'acting'])

/** What the run did after the last yes, in the words every place gives a run's stage, without naming the Approvers again. */
function afterYes(facts: StageFacts, nameOf: NameOf): string {
  if (WRITING.has(facts.state)) return `${stageWords({ ...facts, state: 'acting' }, nameOf)}…`
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
      const head = `Approved by ${standing.by.map(nameOf).join(', then ')}${when(standing.at)}`
      if (facts?.state === 'lost') return `${head}, but ${LOST_TAIL}`
      return facts ? `${head}. ${afterYes(facts, nameOf)}` : `${head}.`
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
