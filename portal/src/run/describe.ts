import { connectorLabel } from '../api/labels'
import { formatClock, formatTime } from '../ui/format'
import type { Figure, Gate, Headline, Items, ParcelForm, Stop, StopCaption, StopState } from './track'

/**
 * Short words for the steps agents report, keyed by agent_step_*.data.step. A step with no row shows its
 * event's summary. `source` is the connector the step reads, for the failure caption.
 */
interface StepLabel {
  readonly source?: string
  /** The caption under the agent stop while the step runs. */
  readonly running: (summary: string) => string
  /** The headline while the agents work on it. */
  readonly doing: string
  /** The headline once the step found something. */
  readonly found?: (count: number) => string
}

const STEP_LABELS: Readonly<Record<string, StepLabel>> = {
  fetch_releases: { source: 'github', running: () => 'Reading GitHub', doing: 'Looking for new releases' },
  find_new: {
    // The summary names the last known tag: "...comparing them with the last known tag 1.2.14."
    running: (summary) => {
      const version = /\d+\.\d+\.\d+/.exec(summary)?.[0]
      return version ? `Comparing with ${version}` : summary
    },
    doing: 'Looking for new releases',
    found: (count) => `Found ${count} new release${count === 1 ? '' : 's'}`,
  },
}

function labelOf(step: string | null): StepLabel | undefined {
  return step === null ? undefined : STEP_LABELS[step]
}

/** "Bob", "Bob and Carol", "Bob, Carol and Dave". */
function names(list: readonly string[]): string {
  return list.length <= 1 ? (list[0] ?? '') : `${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}`
}

function numberWords(count: number): string {
  return count === 1 ? 'one' : String(count)
}

function itemsWords(items: Items): string {
  return items.is === 'chips' ? items.items.join(', ') : `${items.count} found`
}

export interface Viewer {
  /** The approval record says this person may decide the open step (you_can_decide). */
  readonly canDecide: boolean
}

/** A few words of state, for the big line at the top of the Tracker. */
export function headlineWords(headline: Headline, viewer: Viewer): string {
  switch (headline.is) {
    case 'not_started':
    case 'starting':
      return 'Starting'
    case 'working':
      return labelOf(headline.step?.step ?? null)?.doing ?? 'Working'
    case 'found':
      return labelOf(headline.step)?.found?.(headline.count) ?? `Found ${headline.count}`
    case 'drafting':
      return headline.noun === '' ? 'Drafting' : `Drafting ${numberWords(headline.count)} ${headline.noun}${headline.count === 1 ? '' : 's'}`
    case 'waiting':
      return viewer.canDecide ? 'Waiting for your approval' : 'Waiting for an Approver'
    case 'approved':
      return headline.by.length > 0 ? `Approved by ${names(headline.by)}` : 'Approved'
    case 'written': {
      const [only] = headline.lines
      if (headline.lines.length === 1 && only) return `${only.reference} is in ${connectorLabel(only.connector)}`
      const to = [...new Set(headline.lines.map((line) => connectorLabel(line.connector)))]
      return to.length > 0 ? `Written to ${names(to)}` : 'Written'
    }
    case 'nothing_to_write':
      return 'Nothing to write'
    case 'declined':
      return `Declined by ${headline.by}`
    case 'stopped':
      return 'The run stopped'
  }
}

/** The words under a stop. A waiting counter that is sped up also shows SPED_UP_WORDS beside them. */
export function captionWords(caption: StopCaption): string {
  switch (caption.is) {
    case 'none':
      return ''
    case 'time':
      return formatTime(new Date(caption.at).toISOString())
    case 'step':
      return labelOf(caption.step)?.running(caption.summary) ?? caption.summary
    case 'found':
      return itemsWords(caption.items)
    case 'stopped': {
      const source = labelOf(caption.step)?.source
      return source && caption.errorType === 'UpstreamUnavailable' ? `${connectorLabel(source)} unavailable` : 'Stopped here'
    }
    case 'needs_person':
      return 'Needs a person'
    case 'waiting':
      return `Waiting ${formatClock(caption.elapsedMs)}`
    case 'approved':
      return `Approved by ${names(caption.by)}`
    case 'declined':
      return `Declined by ${caption.by}`
    case 'write':
      return WRITE_WORDS[caption.status]
    case 'not_needed':
      return 'Not needed'
  }
}

const WRITE_WORDS: Readonly<Record<Extract<StopCaption, { is: 'write' }>['status'], string>> = {
  not_yet: 'Nothing written yet',
  writing: 'Writing',
  written: 'Written',
  blocked: 'Blocked',
  none_written: 'Nothing written',
}

/** The flag beside a waiting counter that runs faster than the wall. */
export const SPED_UP_WORDS = 'Sped up'

/** The quiet line under the gate when the Teams post failed, beside a link to the approval page. */
export function teamsWords(gate: Gate): string | null {
  return gate.teamsFailed ? 'Teams post failed' : null
}

export function parcelWords(form: ParcelForm): string {
  switch (form.is) {
    case 'request':
      return 'Request'
    case 'found':
      return itemsWords(form.items)
    case 'draft':
      return form.noun === '' ? 'Draft' : `Draft ${form.noun}${form.count > 1 ? 's' : ''}`
    case 'written':
      return form.references.join(', ')
    case 'declined':
      return 'Not written'
    case 'stopped':
      return 'Stopped'
  }
}

const STATE_WORDS: Readonly<Record<StopState, string>> = {
  passed: 'Finished',
  current: 'The work is here',
  future: 'Not reached',
  failed: 'Stopped here',
  done: 'Done',
  not_needed: 'Not needed',
}

/**
 * A stop for a screen reader, after its name: "The work is here: Draft ticket. Waiting 2:41. Sped up."
 * parcel is the parcel's form when the parcel stands on this stop.
 */
export function stopWords(stop: Stop, parcel: ParcelForm | null): string {
  const state = parcel ? `${STATE_WORDS[stop.state]}: ${parcelWords(parcel)}` : STATE_WORDS[stop.state]
  const caption = captionWords(stop.caption)
  const spedUp = stop.caption.is === 'waiting' && stop.caption.spedUp ? SPED_UP_WORDS : ''
  return [state, caption === STATE_WORDS[stop.state] ? '' : caption, spedUp].filter((words) => words !== '').join('. ') + '.'
}

const STATUS_WORDS: Readonly<Record<Extract<Figure, { is: 'agent' }>['status'], string>> = {
  present: 'here',
  working: 'working',
  done: 'done',
  stopped: 'stopped',
}

/** A figure for a screen reader: "Release checker, working", "Team approver, waiting for a decision", "Bob, approved". */
export function figureWords(figure: Figure): string {
  switch (figure.is) {
    case 'agent':
      return `${figure.name}, ${STATUS_WORDS[figure.status]}`
    case 'person':
      return `${figure.name}, ${figure.verdict === null ? 'started the run' : figure.verdict === 'approve' ? 'approved' : 'declined'}`
    case 'seat':
      return `${figure.label}, ${figure.open ? 'waiting for a decision' : 'after the step before'}`
  }
}

/** A proposal's action line split at its first colon: "Create Jira ticket in MOCK: New releases" gives the action and the title. */
export function splitActionLine(line: string): { readonly action: string | null; readonly title: string } {
  const colon = line.indexOf(': ')
  if (colon < 1 || colon + 2 >= line.length) return { action: null, title: line }
  return { action: line.slice(0, colon), title: line.slice(colon + 2) }
}
