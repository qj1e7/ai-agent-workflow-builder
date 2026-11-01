import { OPEN_RUN_AGAIN_WORDS } from '../../api/errors'
import { connectorLabel, refusalLabel, starterName } from '../../api/labels'
import type { SessionKind } from '../../api/session'
import type { Refusal, Trigger, WriteActionView } from '../../api/types'
import { PRODUCT } from '../../shell/product'
import type { LiveRun } from './liveRun'
import type { AgentRef, ChatItem, RunModel, Station } from './runModel'

export type NameOf = (id: string) => string

export function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`
}

export function andList(items: readonly string[]): string {
  if (items.length < 2) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items.at(-1) ?? ''}`
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

export function lineOf(item: ChatItem, nameOf: NameOf, trigger: Trigger): Line {
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
      return { speaker: app, text: trigger === 'schedule' ? 'Done. Nothing was written. The next check asks again.' : 'Done. Nothing was written.', tone: 'plain' }
    case 'stopped':
      return {
        speaker: platform,
        text: item.stage === 'acting' ? 'The run stopped while writing.' : 'The run stopped. Nothing was written.',
        tone: 'bad',
      }
  }
}

function changesOf(actions: readonly Pick<WriteActionView, 'connector' | 'operation'>[], n: number): { noun: string; tickets: boolean } {
  const tickets = actions.length > 0 && actions.every((action) => action.operation === 'create_ticket')
  return { noun: count(n, tickets ? 'ticket' : 'change'), tickets }
}

export interface Headline {
  readonly text: string
  readonly pill: { readonly label: string; readonly tone: 'wait' | 'bad' | 'ok' | 'off' | 'new' }
}

export function headlineOf(model: RunModel, stations: readonly Station[], proposal: readonly WriteActionView[] | null): Headline {
  const { phase } = model
  switch (phase.state) {
    case 'pending':
      return { text: 'Starting the run', pill: { label: 'Working', tone: 'new' } }
    case 'working':
    case 'proposed':
      return { text: 'The agents are working', pill: { label: 'Working', tone: 'new' } }
    case 'awaiting_approval': {
      const pill = { label: 'Waiting for a yes', tone: 'wait' } as const
      if (!proposal) return { text: 'Waiting for a yes', pill }
      const { noun } = changesOf(proposal, proposal.length)
      return { text: `${noun} ${proposal.length === 1 ? 'is' : 'are'} waiting for a yes`, pill }
    }
    case 'acting':
      return { text: 'Writing what was approved', pill: { label: 'Working', tone: 'new' } }
    case 'succeeded': {
      if (phase.outcome === 'nothing_to_write' || model.written.length === 0) return { text: 'Done, nothing to write', pill: { label: 'Done', tone: 'ok' } }
      const { noun, tickets } = changesOf(model.written, model.written.length)
      const where = connectorLabel(model.written[0]?.connector ?? '')
      return { text: `${noun} ${tickets ? 'created' : 'written'} in ${where}`, pill: { label: 'Done', tone: 'ok' } }
    }
    case 'rejected':
      return { text: 'Declined, nothing was written', pill: { label: 'Declined', tone: 'off' } }
    case 'failed': {
      const failed = stations.find((station) => station.state === 'fail')
      return { text: failed ? `Stopped at ${failed.label}` : 'The run stopped', pill: { label: 'Stopped', tone: 'bad' } }
    }
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

export function proposalTitle(actions: readonly WriteActionView[]): string {
  const project = sameTicketProject(actions)
  if (project) return `${count(actions.length, 'ticket')} will be created in Jira project ${project}`
  const where = new Set(actions.map((action) => connectorLabel(action.connector)))
  return `${count(actions.length, 'change')} will be written${where.size === 1 ? ` in ${[...where].join('')}` : ''}`
}

export function approveLabel(actions: readonly WriteActionView[]): string {
  return sameTicketProject(actions) ? `Approve ${count(actions.length, 'ticket')}` : 'Approve'
}

/** How the signed-in person is tied to the run. */
export interface Party {
  readonly startedIt: boolean
  readonly retriedIt: boolean
  readonly schedule: boolean
}

const NOBODY = ' Nobody approves their own work.'

export function lockWords(whyNot: Refusal | null, party: Party | null): string {
  switch (whyNot) {
    case 'own_work': {
      let why = 'This run is your own work, so you can’t approve it.'
      if (party?.startedIt) why = party.schedule ? 'Your schedule started this run, so you can’t approve it.' : 'You started this run, so you can’t approve it.'
      else if (party?.retriedIt) why = 'You retried this run, so you can’t approve it.'
      else if (party) why = 'You own this workflow, so you can’t approve its runs.'
      return `${why}${NOBODY}`
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
