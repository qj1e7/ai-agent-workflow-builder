import { connectorLabel } from '../../api/labels'
import type { ApprovalActionView, ApprovalStepView, Refusal, WriteActionView } from '../../api/types'
import { releasedOn, sinceWhen } from '../workflows/times'
import { approvalTitle } from './approvalWords'
import type { Release } from './runModel'
import { andList, count, lockWords, runPill, type NameOf, type Party, type RunState, type StageFacts, type StageTone } from './words'

/**
 * What the run page says first, each line built by code from the run's own facts. Nothing here is the agents' words: those wait
 * under "Show agent messages", and the approval is decided on the ticket, never on a summary.
 */

const SOFTWARE = /^(.+?)\s+(?:release|version)\s+check$/i

/** The software a workflow checks, from its name: "FastAPI" from "FastAPI release check". Null when the name does not say. */
function softwareIn(useCaseName: string): string | null {
  return SOFTWARE.exec(useCaseName.trim())?.[1] ?? null
}

/**
 * "FastAPI 0.165.0 is out (18 Nov).", from the release the run read. The day shows only when the read carried one, and it is never
 * guessed. A workflow that watches many pieces of software has no one release to name, so it has no line.
 */
export function foundLine(release: Release | null, useCaseName: string, template: string | undefined, now: Date): string | null {
  if (release === null || template === 'software_watchlist') return null
  const name = softwareIn(useCaseName)
  const day = release.at !== null && !Number.isNaN(Date.parse(release.at)) ? ` (${releasedOn(release.at, now)})` : ''
  return `${name ?? 'Version'} ${release.version} is out${day}.`
}

/** Where the run is with its writes: it wants to, is doing it, did it, or wanted to and was declined. */
export type Tense = 'wants' | 'doing' | 'did' | 'wanted'

const TENSES: Readonly<Partial<Record<RunState, Tense>>> = { awaiting_approval: 'wants', acting: 'doing', succeeded: 'did', rejected: 'wanted', expired: 'wanted', lost: 'wanted' }

/** The tense of what a run wants to do, in each state that holds a request, so an expired or lost run keeps its ticket and questions. Undefined before there is a request. */
export function tenseOf(state: RunState): Tense | undefined {
  return TENSES[state]
}

const isTicket = (action: Pick<WriteActionView, 'connector' | 'operation'>) => action.connector === 'jira' && action.operation === 'create_ticket'

function inWhere(actions: readonly Pick<ApprovalActionView, 'connector'>[]): string {
  const where = new Set(actions.map((action) => connectorLabel(action.connector)))
  return where.size === 1 ? ` in ${[...where].join('')}` : ''
}

/** "This run wants to create 1 Jira ticket in MOCK:", the line over the ticket preview. */
export function wantsLine(actions: readonly Pick<ApprovalActionView, 'connector' | 'operation' | 'target'>[], tense: Tense): string {
  const tickets = actions.length > 0 && actions.every(isTicket)
  const projects = [...new Set(actions.flatMap((action) => (typeof action.target['project'] === 'string' ? [action.target['project']] : [])))]
  const where = tickets ? (projects.length === 1 ? ` in ${projects.join('')}` : '') : inWhere(actions)
  const what = tickets ? count(actions.length, 'Jira ticket') : count(actions.length, 'change')
  const verb = tickets
    ? { wants: 'wants to create', doing: 'is creating', did: 'created', wanted: 'wanted to create' }
    : { wants: 'wants to write', doing: 'is writing', did: 'wrote', wanted: 'wanted to write' }
  return `This run ${verb[tense]} ${what}${where}:`
}

const GIST_MAX = 100

/** A write as a small preview: its title, then the first line of its text, cut at a word so it fits on one line. */
export function previewOf(action: ApprovalActionView): { readonly title: string; readonly gist: string | null } {
  const given = action.fields['title']
  const title = typeof given === 'string' && given.trim() !== '' ? given.trim() : approvalTitle([action])
  const body = action.fields['body']
  const first = (typeof body === 'string' ? body : '')
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line !== '')
  if (first === undefined) return { title, gist: null }
  if (first.length <= GIST_MAX) return { title, gist: first }
  const cut = first.slice(0, GIST_MAX - 1)
  const word = cut.lastIndexOf(' ')
  return { title, gist: `${(word > 0 ? cut.slice(0, word) : cut).trimEnd()}…` }
}

const WHY_NOT: Partial<Record<Refusal, string>> = {
  own_work: 'You can’t approve your own run.',
  decided_earlier_step: 'You approved the step before, so another Approver decides this one.',
  not_an_approver: 'Only an Approver can decide.',
  not_eligible: 'You aren’t one of the people who can decide this step.',
}

/** Only the person who started the run reads "You can’t approve your own run." An owner or someone who retried it gets their own reason. */
function whyOf(whyNot: Refusal, party: Party | null): string | undefined {
  if (whyNot === 'own_work') return party?.startedIt ? WHY_NOT.own_work : lockWords(whyNot, party)
  return WHY_NOT[whyNot]
}

const stepAt = (steps: readonly ApprovalStepView[]) => steps.find((step) => step.status === 'open' || step.status === 'waiting')

/**
 * "An Approver decides in Teams (asked 9:01)." and, for someone who may not decide, why not them: the person who started the run
 * reads "You can’t approve your own run." The time is when the platform put it in Teams, and is left out until it has.
 */
export function decidesLine({ steps, canDecide, whyNot, party, now }: { steps: readonly ApprovalStepView[]; canDecide: boolean; whyNot: Refusal | null; party: Party | null; now: Date }): string {
  const open = stepAt(steps)
  const where =
    open?.post === 'failed'
      ? 'An Approver decides on this page. Teams could not be reached.'
      : open?.post === 'sent' && open.sent_at
        ? `An Approver decides in Teams (asked ${sinceWhen(open.sent_at, now)}).`
        : 'An Approver decides in Teams.'
  const why = !canDecide && whyNot !== null ? whyOf(whyNot, party) : undefined
  return why ? `${where} ${why}` : where
}

/** Who ran it, after the workflow's name on the top line: "run by Carol", or "run on its schedule". */
export function runByWords(trigger: 'person' | 'schedule', startedBy: string | null, nameOf: NameOf): string {
  if (trigger === 'schedule') return 'run on its schedule'
  return startedBy ? `run by ${nameOf(startedBy)}` : 'run'
}

/**
 * The status on the right of the top line, in approval words. Writing after an approval names who approved. Everywhere else it is
 * the run's own pill, so the card, the panel and the page say the same.
 */
export function statusOf(facts: StageFacts, nameOf: NameOf): { readonly label: string; readonly tone: StageTone } {
  if (facts.state === 'acting' && facts.approvedBy.length > 0) return { label: `Approved by ${andList(facts.approvedBy.map(nameOf))}`, tone: 'new' }
  return runPill(facts)
}

/** What a run that has no approval says while it goes: the agents are working, or the run is trying again. */
export function workingLine(facts: { readonly retried?: boolean }): string {
  return facts.retried ? 'Retrying. This page updates as the agents go.' : 'The agents are working. This page updates as they go.'
}
