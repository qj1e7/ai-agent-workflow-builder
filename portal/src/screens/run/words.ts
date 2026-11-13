import { OPEN_RUN_AGAIN_WORDS } from '../../api/errors'
import { connectorLabel, failureReasonLabel, refusalLabel, starterName } from '../../api/labels'
import { nextRunAt } from '../workflows/times'
import type { SessionKind } from '../../api/session'
import type { ApprovalActionView, ApprovalStepView, Day, FailureReason, Refusal, RunView, UseCaseView, WriteActionView } from '../../api/types'
import { PRODUCT } from '../../shell/product'
import type { LiveRun } from './liveRun'
import type { AgentRef, ChatItem, Declined, PlanBlock, RunModel } from './runModel'

export type NameOf = (id: string) => string

export function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`
}

export function andList(items: readonly string[]): string {
  if (items.length < 2) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items.at(-1) ?? ''}`
}

/** One closing full stop, unless the words bring their own, as the platform writes it. */
export function sentence(text: string): string {
  return /[.!?…]$/.test(text) ? text : `${text}.`
}

/** Who declined, in the short form a list's line has room for. */
export function declinedBy(declined: Pick<Declined, 'by'>, nameOf: NameOf): string {
  return `Declined by ${nameOf(declined.by)}`
}

/** What the decline left, with the reason when there is one. */
export function declineTail(declined: Pick<Declined, 'reason'>): string {
  return `Nothing was written.${declined.reason ? ` Reason: ${sentence(declined.reason)}` : ''}`
}

/** What the person who declined reads at the bottom of the page right after: "Declined. Nothing was written. Reason: Wrong version." */
export function declinedNowWords(declined: Pick<Declined, 'reason'>): string {
  return `Declined. ${declineTail(declined)}`
}

/**
 * A declined run's record, in the same words everywhere it shows: "Declined by Bob. Nothing was written. Reason: Wrong version.",
 * or "Approved by Bob, then declined by Alice. ..." when a first yes came before. It never names a result or a ticket.
 */
export function declinedRecord(declined: Declined, nameOf: NameOf): string {
  const head = declined.approvedBy.length > 0 ? `Approved by ${declined.approvedBy.map(nameOf).join(', then ')}, then declined by ${nameOf(declined.by)}` : declinedBy(declined, nameOf)
  return `${head}. ${declineTail(declined)}`
}

/** When a declined run's workflow runs next, from its schedule. */
export interface NextRun {
  readonly at: string
  readonly zone: string | undefined
}

/**
 * What happens after a decline, said after the record wherever it shows (spec 10.5), and only what the platform will do: a test run
 * waits for its owner, and a scheduled workflow runs again, the watchlist proposing its tickets again at its next check. Null when
 * nothing is due, as for a paused workflow or one with no schedule.
 */
export function declinedNext(run: { readonly test: boolean; readonly watchlist: boolean }, next: NextRun | null, now: Date): string | null {
  if (run.test) return 'Change what it does, or run the test again.'
  if (!next) return null
  const when = nextRunAt(next.at, now, next.zone)
  return run.watchlist ? `The tickets will be proposed again at the next check, ${when}.` : `It runs again ${when}.`
}

/** The record with what happens next, as the run page, the side panel and the watchlist give it. */
export function declinedWithNext(declined: Declined, next: string | null, nameOf: NameOf): string {
  return next ? `${declinedRecord(declined, nameOf)} ${next}` : declinedRecord(declined, nameOf)
}

/** The record's facts from a request's steps, as the run and approval routes give them. Null unless a step was declined. */
export function declinedOfSteps(steps: readonly ApprovalStepView[]): Declined | null {
  const declined = steps.find((step) => step.status === 'declined')
  if (!declined?.decided_by) return null
  const approvedBy = steps.filter((step) => step.index < declined.index && step.status === 'approved' && step.decided_by).map((step) => step.decided_by ?? '')
  return { by: declined.decided_by, approvedBy, reason: declined.reason ?? null }
}

export function writeLabel(connector: string | null): string {
  return connector ? `Write in ${connectorLabel(connector)}` : 'Write the changes'
}

const TIME_ZONE = 'Asia/Singapore'
const dayAndTime = new Intl.DateTimeFormat('en-GB', { weekday: 'short', hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone: TIME_ZONE })

/** "Fri 9:14", in Singapore time. */
export function shortTime(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const part = (type: Intl.DateTimeFormatPartTypes) => dayAndTime.formatToParts(at).find((p) => p.type === type)?.value ?? ''
  return `${part('weekday')} ${Number(part('hour'))}:${part('minute')}`
}

const logParts = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone: TIME_ZONE })

/** "Tue 27 Oct" and "8:00", built from their parts, because browsers differ on the commas and the leading zero. */
function dayAndClock(at: number): { day: string; clock: string } {
  const parts = logParts.formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return { day: `${part('weekday')} ${part('day')} ${part('month')}`, clock: `${Number(part('hour'))}:${part('minute')}` }
}

/**
 * When each entry in a run's log happened, in Singapore time (spec 10.2). The first says its day, "Tue 27 Oct, 8:00", and
 * the rest only the time, unless the day changed. "X joined" marks where agents come in, so it has no time of its own.
 */
export function logTimes(items: readonly ChatItem[]): ReadonlyMap<number, string> {
  const timed = items.filter((item) => item.kind !== 'joined')
  const firstDay = timed[0] ? dayAndClock(timed[0].at).day : ''
  return new Map(
    timed.map((item, index) => {
      const { day, clock } = dayAndClock(item.at)
      return [item.seq, index === 0 || day !== firstDay ? `${day}, ${clock}` : clock]
    }),
  )
}

export type Speaker =
  | { readonly kind: 'app' }
  | { readonly kind: 'platform' }
  | { readonly kind: 'gate' }
  | { readonly kind: 'agent'; readonly agent: AgentRef }

export type Tone = 'plain' | 'ok' | 'bad' | 'wait'

export interface Line {
  readonly speaker: Speaker
  readonly text: string
  readonly tone: Tone
}

export function speakerName(speaker: Speaker): string {
  switch (speaker.kind) {
    case 'app':
      return PRODUCT
    case 'platform':
      return 'Platform'
    case 'gate':
      return 'Approval gate'
    case 'agent':
      return speaker.agent.display
  }
}

const app = { kind: 'app' } as const
const platform = { kind: 'platform' } as const
const gate = { kind: 'gate' } as const

function wroteWords(operation: string | null, connector: string, refs: readonly string[]): string {
  const where = connectorLabel(connector)
  return operation?.startsWith('create_') ? `Created ${andList(refs)} in ${where}.` : `Wrote ${andList(refs)} in ${where}.`
}

/** A line of the run's chat. `declinedNext` is what happens after a decline, from declinedNext. */
export function lineOf(item: ChatItem, nameOf: NameOf, declinedNext: string | null): Line {
  switch (item.kind) {
    case 'started':
      return { speaker: app, text: `${starterName(nameOf(item.by), item.trigger)} started the run.`, tone: 'plain' }
    case 'joined':
      return { speaker: app, text: `${andList(item.agents.map((agent) => agent.display))} joined`, tone: 'plain' }
    case 'said':
      return { speaker: { kind: 'agent', agent: item.speaker }, text: item.text, tone: item.bad ? 'bad' : 'plain' }
    case 'asked':
      if (item.posted === false && item.channel) {
        return { speaker: gate, text: `Could not post in Teams, in ${item.channel}. An Approver can still decide on this page.`, tone: 'bad' }
      }
      return {
        speaker: gate,
        text: item.channel
          ? `Asked for a yes in Teams, in ${item.channel}. Nothing is written until an Approver says yes.`
          : 'Waiting for an Approver to say yes. Nothing is written until then.',
        tone: 'wait',
      }
    case 'decided': {
      const who = nameOf(item.by)
      const as = item.step ? ` as ${item.step}` : ''
      return item.verdict === 'approve'
        ? { speaker: gate, text: `${who} approved${as}.`, tone: 'ok' }
        : { speaker: gate, text: `${who} declined${as}.`, tone: 'bad' }
    }
    case 'written':
      return { speaker: platform, text: wroteWords(item.operation, item.connector, item.refs), tone: 'plain' }
    case 'denied':
      return { speaker: platform, text: 'The safety checker stopped the write. Nothing was written.', tone: 'bad' }
    case 'retried':
      return { speaker: app, text: item.by ? `${nameOf(item.by)} retried the run.` : 'The run was retried.', tone: 'plain' }
    case 'finished':
      if (item.outcome === 'nothing_to_write') return { speaker: app, text: 'Done. There was nothing to write.', tone: 'ok' }
      return {
        speaker: app,
        text: item.operation === 'create_ticket' ? `Done. ${count(item.count, 'ticket')} created.` : `Done. ${count(item.count, 'change')} written.`,
        tone: 'ok',
      }
    case 'declined':
      return { speaker: app, text: `${declinedRecord(item.record, nameOf)} The run ended.${declinedNext ? ` ${declinedNext}` : ''}`, tone: 'plain' }
    case 'stopped':
      return {
        speaker: platform,
        text: item.stage === 'acting' ? 'The run stopped while writing.' : 'The run stopped. Nothing was written.',
        tone: 'bad',
      }
    case 'reported':
      return { speaker: app, text: `${nameOf(item.by)} reported this run to support.`, tone: 'plain' }
    case 'found':
      return { speaker: app, text: item.text, tone: 'plain' }
    case 'told':
      return { speaker: platform, text: item.line, tone: item.bad ? 'bad' : 'plain' }
  }
}

function stringField(action: WriteActionView, key: string): string | null {
  const value = action.fields[key]
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

export function titleOf(action: WriteActionView): string | null {
  return stringField(action, 'title')
}

export function bodyOf(action: WriteActionView): string | null {
  return stringField(action, 'body')
}

function sameTicketProject(actions: readonly WriteActionView[]): string | null {
  const projects = new Set(actions.map((action) => (action.connector === 'jira' && action.operation === 'create_ticket' ? action.target['project'] : null)))
  const [only] = projects
  return projects.size === 1 && typeof only === 'string' ? only : null
}

/** Ticket keys in the agents' words, only those in a project the proposal writes to, so no other word becomes a link. */
export function ticketKeysIn(text: string, projects: readonly string[]): string[] {
  const keys = text.match(/(?<![A-Za-z0-9_-])[A-Z][A-Z0-9_]*-[1-9][0-9]*(?![A-Za-z0-9_-])/g) ?? []
  return [...new Set(keys.filter((key) => projects.includes(key.slice(0, key.lastIndexOf('-')))))]
}

export function proposalTitle(actions: readonly WriteActionView[]): string {
  const project = sameTicketProject(actions)
  if (project) return `${count(actions.length, 'ticket')} will be created in Jira project ${project}`
  const where = new Set(actions.map((action) => connectorLabel(action.connector)))
  return `${count(actions.length, 'change')} will be written${where.size === 1 ? ` in ${[...where].join('')}` : ''}`
}

/** The approval panel's heading, naming the Jira the tickets go to, so the Approver sees where before saying yes (ADR 0041). */
export function approvalTitle(actions: readonly ApprovalActionView[]): string {
  const sites = new Set(actions.map((action) => action.site_name))
  const [only] = sites
  return sites.size === 1 && only ? `${proposalTitle(actions)} on ${only}` : proposalTitle(actions)
}

export function approveLabel(actions: readonly WriteActionView[]): string {
  return sameTicketProject(actions) ? `Approve ${count(actions.length, 'ticket')}` : 'Approve'
}

/** How the signed-in person is tied to the run, as the approval says it. */
export interface Party {
  readonly ownsIt: boolean
  readonly startedIt: boolean
  readonly retriedIt: boolean
  readonly schedule: boolean
}

const NOBODY = ' Nobody approves their own work.'

function tiesOf(party: Party): string[] {
  const ties: string[] = []
  if (party.startedIt && party.schedule) ties.push('set up the schedule that started this run')
  else {
    if (party.ownsIt) ties.push('set this workflow up')
    if (party.startedIt) ties.push('started this run')
  }
  if (party.retriedIt) ties.push('retried this run')
  return ties
}

export function lockWords(whyNot: Refusal | null, party: Party | null): string {
  switch (whyNot) {
    case 'own_work': {
      const ties = party ? tiesOf(party) : []
      const why = ties.length > 0 ? `You ${andList(ties)}` : 'This run is your own work'
      return `${why}, so another Approver must decide.${NOBODY}`
    }
    case 'not_an_approver':
      return 'Only an Approver can decide.'
    case 'not_open':
      return 'This request is already decided.'
    case 'decided_earlier_step':
      return 'You decided an earlier step, so another Approver must decide this one.'
    case 'not_eligible':
      return 'You are not one of the people who can decide this step.'
    case null:
      return 'You can’t decide this request.'
    default:
      return refusalLabel[whyNot]
  }
}

export const RUN_MISSING = { heading: 'Run not found', lead: 'There is no run at this address.' } as const
export const RUN_PROBLEM = { heading: 'We couldn’t load this run', lead: 'Check your connection, or try again in a moment.' } as const

type Connection = LiveRun['connection']
type ClosedReason = Extract<Connection, { is: 'closed' }>['reason']

export type FeedTrouble =
  | { readonly kind: 'loading' }
  | { readonly kind: 'waiting'; readonly words: string }
  | { readonly kind: 'stop' | 'retry'; readonly heading: string; readonly lead: string }

function closedTrouble(reason: ClosedReason, signIn: SessionKind): FeedTrouble {
  switch (reason) {
    case 'not_found':
      return { kind: 'stop', ...RUN_MISSING }
    case 'forbidden':
      return { kind: 'stop', heading: 'You can’t see this run', lead: 'This account does not have access to it.' }
    case 'signed_out':
      return { kind: 'stop', heading: 'You’re signed out', lead: OPEN_RUN_AGAIN_WORDS[signIn] }
    case 'rejected':
      return { kind: 'retry', ...RUN_PROBLEM }
  }
}

export function feedTroubleOf(connection: Connection, signIn: SessionKind): FeedTrouble {
  switch (connection.is) {
    case 'reconnecting':
      return { kind: 'waiting', words: 'Can’t reach the platform yet. Trying again.' }
    case 'closed':
      return closedTrouble(connection.reason, signIn)
    case 'connecting':
    case 'live':
    case 'settled':
      return { kind: 'loading' }
  }
}

export const CONFLICT_WORDS = 'Another Approver decided this step first.'

const RETIRED: readonly (readonly [RegExp, string])[] = [
  [/\buse cases\b/gi, 'workflows'],
  [/\buse case\b/gi, 'workflow'],
  [/\btemplates\b/gi, 'workflows'],
  [/\btemplate\b/gi, 'workflow'],
  [/\broom leads?\b/gi, 'Planner'],
  [/\brelease checkers?\b/gi, 'Version checker'],
]

export function withCurrentNames(text: string): string {
  return RETIRED.reduce(
    (words, [pattern, plain]) =>
      words.replace(pattern, (found) => {
        const proper = plain.charAt(0) === plain.charAt(0).toUpperCase()
        const capital = found.charAt(0) === found.charAt(0).toUpperCase()
        return proper || !capital ? plain : plain.charAt(0).toUpperCase() + plain.slice(1)
      }),
    text,
  )
}

/** The gate's step on the run line, whatever the plan calls its block. */
export const GATE_STEP = 'Ask for a yes'

/** The sketch's words for the agent steps of the platform's own plans. A step the team named keeps its name. */
const STEP_WORDS: Readonly<Record<string, string>> = {
  crd_version_checker: 'Check release',
}

export function stepWords(block: PlanBlock): string {
  return STEP_WORDS[block.key] ?? block.name
}

const DAY_SHORT: Readonly<Record<Day, string>> = {
  every_day: 'Daily',
  weekdays: 'Weekdays',
  monday: 'Mon',
  tuesday: 'Tue',
  wednesday: 'Wed',
  thursday: 'Thu',
  friday: 'Fri',
  saturday: 'Sat',
  sunday: 'Sun',
}

/** "Daily 8:00", "Weekdays 9:30" or "Mon 13:00": a schedule in the few words a row has room for. */
export function scheduleShort({ day, at }: { readonly day: Day; readonly at: string }): string {
  return `${DAY_SHORT[day]} ${at.replace(/^0/, '')}`
}

export type Schedule = Pick<NonNullable<UseCaseView['schedule']>, 'day' | 'at' | 'time_zone'>

const WEEKDAYS: ReadonlySet<string> = new Set(['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])
/** How late after its time a scheduled run may start and still be that schedule's run. */
const LATE_MINUTES = 10

function scheduleStarted(schedule: Schedule, startedAt: string): boolean {
  const at = new Date(startedAt)
  if (Number.isNaN(at.getTime())) return false
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: schedule.time_zone || TIME_ZONE, weekday: 'long', hour: 'numeric', minute: '2-digit', hourCycle: 'h23' }).formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  const day = part('weekday').toLowerCase()
  const [hour = NaN, minute = NaN] = schedule.at.split(':').map(Number)
  const late = Number(part('hour')) * 60 + Number(part('minute')) - (hour * 60 + minute)
  const onDay = schedule.day === 'every_day' || (schedule.day === 'weekdays' ? WEEKDAYS.has(day) : schedule.day === day)
  return onDay && late >= 0 && late <= LATE_MINUTES
}

/**
 * The run line's first step: the schedule that started the run, "Daily 8:00", or the person who did, "Started by Alice".
 * A schedule changed since the run is not shown on it, so the run reads "On schedule".
 */
export function triggerWords(run: Pick<RunModel, 'trigger' | 'startedBy'>, schedule: Schedule | null, nameOf: NameOf, startedAt: string): string {
  if (run.trigger === 'schedule') return schedule && scheduleStarted(schedule, startedAt) ? scheduleShort(schedule) : 'On schedule'
  return run.startedBy ? `Started by ${nameOf(run.startedBy)}` : 'Started'
}

/** Under the step at work: "Working…", then "Working, 12 s" once a second has passed, then minutes and hours. Small lines say only "…" and "12 s". */
export function workingWords(since: number, now: number, small: boolean): string {
  const seconds = Math.floor((now - since) / 1000)
  if (seconds < 1) return small ? '…' : 'Working…'
  const took = seconds < 60 ? `${seconds} s` : seconds < 3600 ? `${Math.floor(seconds / 60)} min` : `${Math.floor(seconds / 3600)} h`
  return small ? took : `Working, ${took}`
}

/** How a finished run ended, said once under its line. */
export interface Settled {
  readonly tone: 'ok' | 'off'
  readonly text: string
}

function settledWhen(at: number, now: Date): string {
  const { day, clock } = dayAndClock(at)
  return day === dayAndClock(now.getTime()).day ? `at ${clock}` : `on ${day} at ${clock}`
}

function afterYeses(approvedBy: readonly string[], nameOf: NameOf): string {
  const names = approvedBy.map(nameOf)
  if (names.length === 0) return ''
  return names.length === 1 ? ` after ${names.join('')}’s yes` : ` after ${andList(names)} said yes`
}

/** "Bob declined: not this week. Nothing was written.", with a first yes before it when there was one. A quick reason reads on in the sentence; a typed one is kept as typed. */
export function declinedSentence(declined: Declined, nameOf: NameOf, quick: readonly string[]): string {
  const { reason } = declined
  const why = reason ? `: ${sentence(quick.includes(reason) ? reason.charAt(0).toLowerCase() + reason.slice(1) : reason)}` : '.'
  const first = declined.approvedBy.length > 0 ? `${andList(declined.approvedBy.map(nameOf))} said yes, then ` : ''
  return `${first}${nameOf(declined.by)} declined${why} Nothing was written.`
}

/**
 * How a run ended, said after the time: "MOCK-22 created after Bob’s yes", "Bob declined: not this week. Nothing was written." or
 * "No answer. Nothing was written.". Null while the run goes on or after a stop.
 */
export function endedWords(model: RunModel, nameOf: NameOf, quick: readonly string[]): { readonly tone: 'ok' | 'off'; readonly text: string } | null {
  const { phase } = model
  if (phase.state === 'rejected') return { tone: 'off', text: declinedSentence({ by: phase.by, approvedBy: model.approvedBy, reason: model.declineReason }, nameOf, quick) }
  const facts = stageFactsOf(model)
  if (phase.state === 'expired' || phase.state === 'lost') return { tone: 'off', text: stageWords(facts, nameOf) }
  if (phase.state !== 'succeeded') return null
  const done = stageWords({ ...facts, approvedBy: [] }, nameOf)
  return { tone: 'ok', text: facts.count === 0 ? done : `${done}${afterYeses(model.approvedBy, nameOf)}` }
}

/**
 * "Done at 9:04 · MOCK-22 created after Bob’s yes", or "Ended at 9:04 · Bob declined: not this week. Nothing was written.".
 * A quick reason reads on in the sentence. A reason the Approver typed is kept as they typed it. Null while the run goes on or after a stop.
 */
export function settledOf(model: RunModel, nameOf: NameOf, now: Date, quick: readonly string[]): Settled | null {
  const ended = endedWords(model, nameOf, quick)
  if (!ended) return null
  const at = model.chat.findLast((item) => item.kind === 'finished' || item.kind === 'declined')?.at ?? model.reached.findLast((reached) => reached.spot.at === 'done')?.at
  if (at === undefined) return null
  return { tone: ended.tone, text: `${ended.tone === 'off' ? 'Ended' : 'Done'} ${settledWhen(at, now)} · ${ended.text}` }
}

/** The first line over a run's page and panel: "Today’s run, 8:00", "Yesterday’s run, 8:00", or "Run on Tue 27 Oct, 8:00". */
export function runKind(startedAt: string, now: Date): string {
  const at = new Date(startedAt).getTime()
  if (Number.isNaN(at)) return 'Run'
  const { day, clock } = dayAndClock(at)
  const today = dayAndClock(now.getTime()).day
  if (day === today) return `Today’s run, ${clock}`
  if (day === dayAndClock(now.getTime() - 86_400_000).day) return `Yesterday’s run, ${clock}`
  return `Run on ${day}, ${clock}`
}

/** One row of the run page's Step by step: when it happened, and one sentence of what. An agent's own words carry its name. */
export interface LogRow {
  readonly seq: number
  readonly at: number
  readonly time: string
  readonly text: string
  readonly agent: AgentRef | null
  readonly tone: 'plain' | 'bad' | 'wait'
  /** A row the gate's decision lands on, so focus can go to it. */
  readonly gate: boolean
  readonly keys: readonly string[]
  readonly urls: Readonly<Record<string, string>> | undefined
}

const clockParts = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: TIME_ZONE })

/** "8:00:31", in Singapore time. */
export function logClock(at: number): string {
  const parts = clockParts.formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return `${Number(part('hour'))}:${part('minute')}:${part('second')}`
}

/**
 * The run's log in the sketch's words, one sentence a row. What the Step by step shows once: the run line already says who joined and
 * when it finished, so those have no row, and a decline is the one row that says who declined and that nothing was written.
 */
export function logRowsOf(items: readonly ChatItem[], nameOf: NameOf, quick: readonly string[]): LogRow[] {
  const firstDay = items[0] ? dayAndClock(items[0].at).day : ''
  const rows: LogRow[] = []
  const declinedLater = (index: number) => items.slice(index + 1).some((item) => item.kind === 'declined')
  items.forEach((item, index) => {
    let text: string
    let agent: AgentRef | null = null
    let tone: LogRow['tone'] = 'plain'
    switch (item.kind) {
      case 'joined':
      case 'finished':
        return
      case 'decided':
        if (item.verdict === 'decline' && declinedLater(index)) return
        text = item.verdict === 'approve' ? `${nameOf(item.by)} said yes${item.step ? ` as ${item.step}` : ''}.` : `${nameOf(item.by)} declined.`
        break
      case 'declined':
        text = declinedSentence(item.record, nameOf, quick)
        break
      case 'started':
        text = item.trigger === 'schedule' ? 'Started on schedule.' : `${nameOf(item.by)} started the run.`
        break
      case 'asked':
        if (item.posted === false && item.channel) {
          text = `Couldn’t send to Teams, in ${item.channel}. An Approver can still decide on this page.`
          tone = 'bad'
        } else {
          text = item.channel ? 'Asked an Approver for a yes in Teams.' : 'Waiting for an Approver to say yes. Nothing is written until then.'
          tone = 'wait'
        }
        break
      case 'retried':
        text = item.by ? `${nameOf(item.by)} retried the run, after a short wait.` : 'The run was retried, after a short wait.'
        break
      default: {
        const line = lineOf(item, nameOf, null)
        text = line.text
        tone = line.tone === 'bad' ? 'bad' : 'plain'
        if (line.speaker.kind === 'agent') agent = line.speaker.agent
      }
    }
    const { day, clock } = { day: dayAndClock(item.at).day, clock: logClock(item.at) }
    rows.push({
      seq: item.seq,
      at: item.at,
      time: day === firstDay ? clock : `${day}, ${clock}`,
      text,
      agent,
      tone,
      gate: item.kind === 'decided',
      keys: item.kind === 'written' && item.connector === 'jira' ? item.refs : [],
      urls: item.kind === 'written' ? item.urls : undefined,
    })
  })
  return rows
}

export type RunState = RunView['state']

/**
 * What a run needs to say where it stands. Every place that names a run's state reads it: the card, the panel, the page, the chat's
 * decided card, a list's row, the banner, the strip and Recent runs, so they never disagree.
 */
export interface StageFacts {
  readonly state: RunState
  /** What the run wrote when it succeeded, or what it proposes while it waits or writes. */
  readonly count: number
  /** Whether it creates tickets, from the operation, so a page it updates is never called a ticket. */
  readonly tickets: boolean
  readonly approvedBy: readonly string[]
  readonly declinedBy: string | null
  readonly reason: FailureReason | null
  /** A run retried after a stop says Retrying until it reaches the yes. Only the run's own events know it. */
  readonly retried?: boolean
  /** What it wrote, by the names its own events give, so a run followed live says "MOCK-22 created". */
  readonly refs?: readonly string[]
}

/** A run's facts when only its state and a few facts are known, as the strip and the chat's decided card know it. */
export function factsOf(state: RunState, known: Partial<StageFacts> = {}): StageFacts {
  return { state, count: 0, tickets: true, approvedBy: [], declinedBy: null, reason: null, ...known }
}

/** A run's facts from its own events, for the card, the panel and the page. */
export function stageFactsOf(model: RunModel): StageFacts {
  const { phase } = model
  const operations = model.written.length > 0 ? model.written.map((item) => item.operation) : model.operations
  return {
    state: phase.state,
    count: phase.state === 'succeeded' ? model.written.length : Math.max(model.proposed, model.written.length),
    tickets: operations.every((operation) => operation === 'create_ticket'),
    approvedBy: model.approvedBy,
    declinedBy: phase.state === 'rejected' ? phase.by : null,
    reason: phase.state === 'failed' ? phase.reason : null,
    retried: model.chat.some((item) => item.kind === 'retried'),
    refs: model.written.map((item) => item.ref).filter((ref) => ref !== ''),
  }
}

/**
 * Where the run stands, in a short phrase that reads after "last run today," and on its own: "Waiting for a yes", "Retrying",
 * "1 ticket created, approved by Bob", or "MOCK-22 created" when the run's events name what it wrote.
 */
export function stageWords(run: StageFacts, nameOf: NameOf): string {
  const noun = (n: number) => count(n, run.tickets ? 'ticket' : 'change')
  switch (run.state) {
    case 'failed':
      return run.reason ? failureReasonLabel[run.reason] : 'Stopped'
    case 'awaiting_approval':
      return 'Waiting for a yes'
    case 'skipped':
      return 'Skipped. An earlier run is still waiting for a yes.'
    case 'expired':
      return 'No answer. Nothing was written.'
    case 'lost':
      return 'Approved, but n8n lost the run. Nothing was written.'
    case 'pending':
    case 'working':
    case 'proposed':
      return run.retried ? 'Retrying' : 'Running'
    case 'acting':
      return run.tickets ? `Creating the ${run.count > 1 ? 'tickets' : 'ticket'}` : 'Writing the changes'
    case 'succeeded': {
      if (run.count === 0) return 'Nothing new to write'
      const refs = run.refs ?? []
      const approvers = run.approvedBy.map(nameOf)
      return `${refs.length > 0 ? andList(refs) : noun(run.count)} ${run.tickets ? 'created' : 'written'}${approvers.length > 0 ? `, approved by ${andList(approvers)}` : ''}`
    }
    case 'rejected':
      return `${run.declinedBy ? declinedBy({ by: run.declinedBy }, nameOf) : 'Declined'}. Nothing was written.`
  }
}

export type StageTone = 'ok' | 'wait' | 'bad' | 'new' | 'quiet'

/** The one pill a run has: Stopped, Running, Waiting for a yes, Done, Nothing new or Declined. */
export function runPill(run: StageFacts): { readonly label: string; readonly tone: StageTone } {
  switch (run.state) {
    case 'failed':
      return { label: 'Stopped', tone: 'bad' }
    case 'awaiting_approval':
      return { label: 'Waiting for a yes', tone: 'wait' }
    case 'pending':
    case 'working':
    case 'proposed':
    case 'acting':
      return { label: 'Running', tone: 'new' }
    case 'succeeded':
      return run.count === 0 ? { label: 'Nothing new', tone: 'quiet' } : { label: 'Done', tone: 'ok' }
    case 'rejected':
      return { label: 'Declined', tone: 'quiet' }
    case 'skipped':
      return { label: 'Skipped', tone: 'quiet' }
    case 'expired':
      return { label: 'No answer', tone: 'quiet' }
    case 'lost':
      return { label: 'Lost', tone: 'bad' }
  }
}
