import { ApiError } from '../../api/client'
import { failureReasonLabel } from '../../api/labels'
import type { CapabilityView, Day, FailureReason, Refusal, ScheduleHold, ScheduleView, VersionSourceView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import type { NextRun } from '../run/words'
import { dateAndClock, lineWhen, scheduleZoneName, timesZone } from '../workflows/times'

/** The Software page and the side panel both refresh the watchlist this often. */
export const REFRESH_MS = 15_000

/** The places releases are read from, from the capability registry, and those of them working now. */
function releaseSources(capabilities: readonly CapabilityView[]): { readonly all: string; readonly working: string } {
  const sources = capabilities.filter((c) => c.id.endsWith('.releases') && c.system !== null)
  const systems = (list: readonly CapabilityView[]) => list.map((c) => c.system).join(' and ')
  return { all: systems(sources), working: systems(sources.filter((c) => c.state === 'ready')) }
}

/** Where releases are read from, said from the capability registry so this page never claims more than How it works does. Null while the registry is not there. */
export function sourcesNote(capabilities: readonly CapabilityView[] | undefined): string | null {
  if (capabilities === undefined) return null
  const { all, working } = releaseSources(capabilities)
  const first = working ? `${working} is the only place we can check today.` : all ? `${all} is the only place we check, and it is not working right now.` : 'No place can be checked right now.'
  const notYet = capabilities.find((c) => c.id === 'registries.check' && (c.state === 'planned' || c.state === 'unsupported'))
  return notYet?.cant ? `${first} We can’t ${notYet.cant} yet.` : first
}

interface Checking {
  readonly scheduled: boolean
  readonly paused: boolean
}

function checkedAgain({ scheduled, paused }: Checking): string {
  if (paused) return 'It is checked again once the watchlist is resumed.'
  return scheduled ? 'It will try again at the next check.' : 'It is checked again when an Operator presses Check now.'
}

export function cantCheckWords(problem: string | null, checking: Checking): string {
  return `${problem ?? 'Can’t check right now.'} ${checkedAgain(checking)}`
}

/** GitHub told the check the saved repository has no home: the row says so, with no way to fix it by button. */
export function notFoundWords(row: Pick<WatchedSoftwareView, 'name' | 'source'>, { operator, scheduled, paused }: Checking & { readonly operator: boolean }): string {
  const skipped = `GitHub can’t find ${row.source.ref}. It may have moved to another repository. ${row.name} stays Can’t check until GitHub finds that address.`
  if (!operator) return `${skipped} An Operator can fix this.`
  return `${skipped} Remove it and add it again at its new address. ${checkedAgain({ scheduled, paused })}`
}

/** GitHub renamed the saved repository and passes the old name on to the new one. */
export function movedWords(row: Pick<WatchedSoftwareView, 'source' | 'moved_to'>): string {
  return `GitHub now calls this project ${row.moved_to}. We saved ${row.source.ref}, and checks still reach it through GitHub’s redirect.`
}

export function askNewAddressWords(row: Pick<WatchedSoftwareView, 'name' | 'moved_to'>): string {
  return `Read ${row.name} from ${row.moved_to} from now on? Only our list changes. Nothing is written to GitHub or Jira.`
}

export const NEW_ADDRESS_ASK = 'Use the new address'

export function movedHeadline(name: string, saved: string, movedTo: string): string {
  return `GitHub moved ${name} from ${saved} to ${movedTo}.`
}

export function notFoundHeadline(name: string, saved: string): string {
  return `GitHub can’t find ${saved}, the address saved for ${name}.`
}

export interface Attention {
  readonly id: string
  readonly name: string
  readonly words: string
}

/** The rows whose address needs a person, in the order of the list. A moved row and a not-found row never overlap. */
export function addressAttentionOf(rows: readonly WatchedSoftwareView[]): Attention[] {
  return rows.flatMap((row) => {
    if (row.moved_to) return [{ id: row.id, name: row.name, words: movedHeadline(row.name, row.source.ref, row.moved_to) }]
    if (row.not_found) return [{ id: row.id, name: row.name, words: notFoundHeadline(row.name, row.source.ref) }]
    return []
  })
}

/** What the Software page lists under Needs attention. The page's heading and the rail's Watchlist count both read it. */
export function watchAttention(rows: readonly WatchedSoftwareView[]): number {
  return decisionsOf(rows).length + addressAttentionOf(rows).length
}

export type StatusTone = 'bad' | 'wait' | 'good' | 'quiet'

export interface SoftwareState {
  /** The pill's words, the same on the Watchlist rows, the panel and the software page. */
  readonly words: string
  readonly tone: StatusTone
  /** Which part of the count line the row counts in. */
  readonly part: LinePart
}

type LinePart = 'newer' | 'gone' | 'cant' | 'current' | 'watching'

/**
 * The state of a watched software in the sketch's words: Can’t find, Newer out, Watching, Up to date. Everything that says a state reads this,
 * so a pill and a count never disagree. A row whose check just failed says Can’t check, because GitHub has not said the address is gone.
 * A row with no version to compare says Watching, never Up to date. The upgrade ticket is a fact on the software page, not a state.
 */
export function stateOf(row: Pick<WatchedSoftwareView, 'status' | 'our_version' | 'not_found'>): SoftwareState {
  switch (row.status) {
    case 'cant_check':
      return row.not_found ? { words: 'Can’t find', tone: 'bad', part: 'gone' } : { words: 'Can’t check', tone: 'bad', part: 'cant' }
    case 'behind':
    case 'awaiting_approval':
    case 'ticket_open':
      return { words: 'Newer out', tone: 'wait', part: 'newer' }
    case 'not_checked':
      return { words: 'Watching', tone: 'quiet', part: 'watching' }
    case 'up_to_date':
      return row.our_version === null ? { words: 'Watching', tone: 'quiet', part: 'watching' } : { words: 'Up to date', tone: 'good', part: 'current' }
  }
}

const RANK: Record<LinePart, number> = { gone: 0, cant: 0, newer: 1, watching: 2, current: 3 }

/** The Watchlist lists what needs a person first: Can’t find, Newer out, Watching, then Up to date. */
export const watchRank = (row: Pick<WatchedSoftwareView, 'status' | 'our_version' | 'not_found'>): number => RANK[stateOf(row).part]

const lineWords: Record<LinePart, (count: number) => string> = {
  newer: (count) => `${count} ${count === 1 ? 'has' : 'have'} a newer version`,
  gone: (count) => `${count} can’t be found`,
  cant: (count) => `${count} can’t be checked`,
  current: (count) => `${count} ${count === 1 ? 'is' : 'are'} up to date`,
  watching: (count) => `${count} watching`,
}

const LINE_ORDER: readonly LinePart[] = ['newer', 'gone', 'cant', 'current', 'watching']

/**
 * The line under the page's title, such as "3 have a newer version · 1 can’t be found · 2 are up to date", from every row on the list, so a
 * search never changes it. Null for an empty list. Every row counts once, in the part its pill names.
 */
export function countLine(rows: readonly WatchedSoftwareView[]): string | null {
  if (rows.length === 0) return null
  return LINE_ORDER.flatMap((part) => {
    const count = rows.filter((row) => stateOf(row).part === part).length
    return count > 0 ? [lineWords[part](count)] : []
  }).join(' · ')
}

/** "today", or the day's date such as "Thu 12 Nov". */
function dayOf(iso: string, now: Date): string {
  const when = lineWhen(iso, now)
  return when.startsWith('Today') ? 'today' : when
}

/**
 * A Watchlist row's second line, as the sketch has it: "1.2.14 → 1.2.16 · checked by Software watchlist". The sketch's "out 5 Nov" is left out,
 * because the platform doesn't keep a release's date. `checkedBy` is null while nothing checks the list: it is paused or has no schedule.
 */
export function softwareLine(row: WatchedSoftwareView, now: Date, checkedBy: string | null): string {
  const { part } = stateOf(row)
  const version =
    part === 'gone'
      ? 'GitHub can’t find it'
      : part === 'cant'
        ? 'Can’t check right now'
        : part === 'newer'
          ? row.our_version !== null && row.newest_version !== null
            ? `${row.our_version} → ${row.newest_version}`
            : `Newest is ${row.newest_version ?? 'not known'}`
          : part === 'current'
            ? `${row.our_version ?? ''}, the newest`
            : row.newest_version !== null
              ? `Newest is ${row.newest_version}`
              : `Added ${dayOf(row.added_at, now)}`
  return `${version} · ${checkedBy ? `checked by ${checkedBy}` : 'not checked automatically'}`
}

/** The side panel's one sentence on where the software stands. Nothing here is guessed: a version nobody knows is said to be unknown. */
export function sentenceFor(row: WatchedSoftwareView): string {
  const { part } = stateOf(row)
  if (part === 'gone') return row.moved_to ? `GitHub now calls this project ${row.moved_to}.` : `GitHub can’t find ${row.source.ref}, and doesn’t say where it moved.`
  if (part === 'cant') return row.newest_version !== null ? `The last check stopped. The newest version it read was ${row.newest_version}.` : 'The last check stopped before it read the newest version.'
  if (row.newest_version === null) return 'Not checked yet. The first check reads the newest release.'
  if (row.our_version === null) return `Newest is ${row.newest_version}. The version you run isn’t known yet.`
  return part === 'current' ? `You run ${row.our_version}, the newest.` : `You run ${row.our_version}. Newest is ${row.newest_version}.`
}

/** The software page's Upgrade ticket fact. `declined` is the latest check's declined record, when an Approver said no to this row's ticket. */
export function ticketFact(row: Pick<WatchedSoftwareView, 'status' | 'open_ticket' | 'our_version' | 'not_found'>, declined: string | null): string {
  if (declined) return declined
  switch (row.status) {
    case 'awaiting_approval':
      return 'Waiting for a yes'
    case 'ticket_open':
      return row.open_ticket ? `${row.open_ticket}, open in Jira` : 'Open in Jira'
    case 'cant_check':
      return 'None yet. The last check stopped before it could tell.'
    case 'up_to_date':
      return row.our_version === null ? 'None yet' : 'Not needed'
    case 'behind':
    case 'not_checked':
      return 'None yet'
  }
}

const SOURCE_NAME: Record<WatchedSoftwareView['source']['kind'], string> = { github: 'GitHub' }

/** What checks a row, as "Checked on GitHub" only while the registry says releases are read there. Otherwise it names only where the project is. */
export function checkedOnWords(kind: WatchedSoftwareView['source']['kind'], capabilities: readonly CapabilityView[] | undefined): string {
  const releases = capabilities?.find((c) => c.id === `${kind}.releases`)
  const where = releases?.system ?? SOURCE_NAME[kind]
  return releases?.state === 'ready' ? `Checked on ${where}` : `On ${where}`
}

export const PAUSED_WORDS = 'Paused. No check runs until an Operator resumes it.'

/** True when the schedule starts checks: it is set, and not held because its owner can no longer run it. */
export function scheduleRuns(schedule: ScheduleView | null | undefined): boolean {
  return schedule != null && !schedule.held
}

const heldWhy: Record<ScheduleHold, string> = {
  owner_removed: 'is no longer on the People list',
  owner_not_an_operator: 'can no longer run workflows',
}

/** Why a held schedule starts nothing, in the words the Software page and the workflow page both show. */
export const TAKE_OVER_WORDS = 'An Operator can take it over by saving the schedule.'

export function heldWords(held: ScheduleHold, ownerName: string, howToRunAgain: string): string {
  const owner = ownerName.trim() || 'its owner'
  return `Not running: ${owner} ${heldWhy[held]}. ${howToRunAgain}`
}

/**
 * What the schedule does next. The view names no next check while the watchlist is paused or the schedule is held, and paused wins over held.
 * The next check is in the schedule's own zone, as on the Workflows list, and always names its zone, as this page always has.
 */
/** When the next check runs, while the schedule will start one. Null while the watchlist is paused, held or has no schedule. */
export function nextCheckOf(view: Pick<WatchlistView, 'state' | 'schedule'> | null): NextRun | null {
  const schedule = view?.schedule
  if (!schedule || view.state === 'paused' || schedule.held || schedule.next_at === null) return null
  return { at: schedule.next_at, zone: schedule.time_zone }
}

export function nextCheckWords(schedule: ScheduleView, paused: boolean): string {
  if (schedule.held && !paused) return heldWords(schedule.held, schedule.owner_name, TAKE_OVER_WORDS)
  if (schedule.next_at === null) return PAUSED_WORDS
  return `Next check ${dateAndClock(schedule.next_at, schedule.time_zone)}, ${timesZone(schedule.time_zone)}.`
}

/** Who checks a watched software and where, from the same registry as the Software page's note. Null while the registry is not there. */
export function checkedByWords(capabilities: readonly CapabilityView[] | undefined): string | null {
  if (capabilities === undefined) return null
  const { all, working } = releaseSources(capabilities)
  if (working) return `The Version checker, on ${working}.`
  return all ? `The Version checker, on ${all}, which is not working right now.` : 'The Version checker. No place can be checked right now.'
}

/** How it's checked says this with or without a schedule. The side panel's When row leaves it out. */
export const ONE_APPROVAL = 'One approval covers all the upgrade tickets.'

export function noScheduleWords({ operator, paused }: { readonly operator: boolean; readonly paused: boolean }): string {
  if (paused) return `No schedule. ${PAUSED_WORDS}`
  return operator ? 'No schedule. Press Check now to check by hand.' : 'No schedule. An Operator can press Check now to check by hand.'
}

export function emptyWords({ operator, scheduled, paused }: { readonly operator: boolean } & Checking): string {
  if (!operator) return 'An Operator can add the tools your team runs.'
  if (paused) return 'Add the tools your team runs. They can be checked once an Operator resumes the watchlist.'
  return scheduled ? 'Add the tools your team runs. Each one is checked at the next check.' : 'Add the tools your team runs, then press Check now to check them.'
}

const dayLabel: Record<Day, string> = {
  every_day: 'every day',
  weekdays: 'every weekday',
  monday: 'every Monday',
  tuesday: 'every Tuesday',
  wednesday: 'every Wednesday',
  thursday: 'every Thursday',
  friday: 'every Friday',
  saturday: 'every Saturday',
  sunday: 'every Sunday',
}

export const DAYS: readonly Day[] = ['every_day', 'weekdays', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

export const dayOption: Record<Day, string> = {
  every_day: 'Every day',
  weekdays: 'Every weekday',
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
}

const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/
const DOT_SEGMENT = /\/\.\.?$/
const VERSION = /^[vV]?\d+\.\d+\.\d+$/
const CLOCK = /^([01][0-9]|2[0-3]):[0-5][05]$/
const NAME_LIMIT = 80

export const REPO_HELP = 'Paste the project’s GitHub link, or type owner/name.'
const REPO_BAD = 'That doesn’t look like a GitHub project. Paste its GitHub link, or type owner/name.'
const REPO_EMPTY = `Type its GitHub repository. ${REPO_HELP}`

type Checked<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly words: string }

/** A pasted GitHub link or owner/name, as the owner/name the platform wants. */
export function repoOf(text: string): string {
  const trimmed = text.trim()
  const link = /github\.com\/([^/\s]+\/[^/\s#?]+)/i.exec(trimmed)
  return (link?.[1] ?? trimmed).replace(/\.git$/i, '').replace(/\/$/, '')
}

export function checkRepo(text: string, watched: readonly string[] = []): Checked<string> {
  const repo = repoOf(text)
  if (repo === '') return { ok: false, words: REPO_EMPTY }
  if (!REPO.test(repo) || DOT_SEGMENT.test(repo)) return { ok: false, words: REPO_BAD }
  if (watched.some((ref) => ref.toLowerCase() === repo.toLowerCase())) return { ok: false, words: `${repo} is already on the list.` }
  return { ok: true, value: repo }
}

export function checkName(text: string, watched: readonly string[] = []): Checked<string> {
  const name = text.trim()
  if (name === '') return { ok: false, words: 'Give the software a name.' }
  if (name.length > NAME_LIMIT) return { ok: false, words: `Keep the name to ${NAME_LIMIT} letters or fewer.` }
  if (watched.some((known) => known.toLowerCase() === name.toLowerCase())) return { ok: false, words: `${name} is already on the list.` }
  return { ok: true, value: name }
}

export const VERSION_HELP = 'Leave it empty if you don’t know. It shows as Not known, and the check tells you about releases newer than the newest one it first reads.'

const VERSION_BAD = 'Type the version as three numbers, such as 1.2.14.'

export function checkVersion(text: string): Checked<string | null> {
  const version = text.trim()
  if (version === '') return { ok: true, value: null }
  if (!VERSION.test(version)) return { ok: false, words: VERSION_BAD }
  return { ok: true, value: version }
}

export interface FormErrors {
  readonly name?: string
  readonly repo?: string
  readonly version?: string
  readonly form?: string
}

const REFUSED_FIELD: Record<string, keyof FormErrors> = { name: 'name', repo: 'repo', our_version: 'version' }
const REFUSED_WORDS: Record<keyof FormErrors, string> = {
  name: `Give the software a name of ${NAME_LIMIT} letters or fewer.`,
  repo: REPO_BAD,
  version: VERSION_BAD,
  form: 'The list is full. Remove software you no longer run, then add this one.',
}

export function addProblems(error: unknown): FormErrors | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null
  const detail = (error.body as { detail?: unknown } | null)?.detail
  if (!Array.isArray(detail)) return null
  const found: Partial<Record<keyof FormErrors, string>> = {}
  for (const problem of detail as { type?: unknown; loc?: unknown }[]) {
    const loc = Array.isArray(problem.loc) ? problem.loc : []
    const field = problem.type === 'watchlist_full' ? 'form' : REFUSED_FIELD[String(loc.at(-1))]
    if (field) found[field] = REFUSED_WORDS[field]
  }
  return Object.keys(found).length > 0 ? found : null
}

export function checkClock(text: string): Checked<string> {
  const at = text.trim()
  return CLOCK.test(at) ? { ok: true, value: at } : { ok: false, words: 'Pick a time on a 5-minute step, such as 9:00.' }
}

export function matches(count: number): string {
  if (count === 0) return 'No matches'
  return count === 1 ? '1 match' : `${count} matches`
}

function matchesQuery(row: WatchedSoftwareView, query: string): boolean {
  const q = query.trim().toLowerCase()
  return q === '' || `${row.name} ${row.source.ref}`.toLowerCase().includes(q)
}

/** Every row stays in Software we watch, so its count is the real number. Only the search narrows it. */
export function rowsMatching(rows: readonly WatchedSoftwareView[], query: string): WatchedSoftwareView[] {
  return rows.filter((row) => matchesQuery(row, query))
}

export interface Decision {
  readonly approvalId: string
  /** How many watched software this one yes covers. */
  readonly software: number
}

/** One decision for the whole check: the tickets of one run wait on one approval, however many rows they came from. */
export function decisionsOf(rows: readonly WatchedSoftwareView[]): Decision[] {
  const counts = new Map<string, number>()
  for (const row of rows) {
    if (row.status === 'awaiting_approval' && row.approval_id) counts.set(row.approval_id, (counts.get(row.approval_id) ?? 0) + 1)
  }
  return [...counts].map(([approvalId, software]) => ({ approvalId, software }))
}

export function decisionTitle(tickets: number): string {
  return `The latest check wants to raise ${tickets} upgrade ${tickets === 1 ? 'ticket' : 'tickets'}.`
}

export const DECISION_NOTE = 'Nothing is written until an Approver says yes.'

/** What the bar says to someone who can't decide it. The platform says why. */
export function waitingWords(whyNot: Refusal | null): string {
  switch (whyNot) {
    case 'own_work':
      return 'Waiting for another Approver. This check is your own work.'
    case 'decided_earlier_step':
      return 'Waiting for another Approver. You decided an earlier step.'
    default:
      return 'Waiting for an Approver.'
  }
}

export function rowDomId(softwareId: string): string {
  return `software-${softwareId}`
}

export function versionSourceWords(source: VersionSourceView | null): string {
  if (source === null) return 'Not known until the first check'
  switch (source.kind) {
    case 'given':
      return 'Given when added'
    case 'first_check':
      return 'Compared from the first check'
    case 'ticket_done':
      return source.ticket ? `From ${source.ticket}, marked Done` : 'From a ticket marked Done'
  }
}

export const NOT_KNOWN = 'Not known'

interface Ours {
  readonly version: string
  readonly note: string
}

/** What the row says the team runs. When nobody knows, it says so, and never shows the newest release in its place. */
export function oursOf(row: WatchedSoftwareView): Ours {
  if (row.our_version !== null) return { version: row.our_version, note: versionSourceWords(row.our_version_source) }
  if (row.compared_from) return { version: NOT_KNOWN, note: `Telling you about releases newer than ${row.compared_from}, the newest the first check read` }
  return { version: NOT_KNOWN, note: 'The first check reads the newest release. Later checks tell you about newer ones' }
}

interface Newest {
  readonly version: string
  readonly note: string | null
}

export function newestOf(row: WatchedSoftwareView): Newest {
  if (row.newest_version === null) return { version: row.status === 'not_checked' ? 'Not checked yet' : 'Not known', note: null }
  const keptFrom = row.status === 'cant_check' ? row.newest_read_at : null
  return { version: row.newest_version, note: keptFrom ? `Last read ${singaporeTime(keptFrom)}` : null }
}

/** "Mon 16 Nov, 9:00", in Singapore time. The midnight hour reads "0:30". */
export function singaporeTime(iso: string): string {
  return dateAndClock(iso)
}

export function clockWords(at: string): string {
  return at.replace(/^0/, '')
}

/** "every Monday", "every weekday". */
export const everyWords = (day: Day): string => dayLabel[day]

export function repeatWords({ day, at }: { readonly day: Day; readonly at: string }): string {
  return `${dayLabel[day]} at ${clockWords(at)}`
}

/** "Checked every Monday at 9:00, set by Carol.", with the schedule's zone after the time when it is not Singapore: "at 9:00 London time". */
export function scheduleWords(schedule: ScheduleView): string {
  const zone = scheduleZoneName(schedule.time_zone)
  return `Checked ${repeatWords(schedule)}${zone ? ` ${zone}` : ''}, set by ${schedule.owner_name}.`
}

export function stoppedWords(reason: FailureReason | null): string {
  if (reason === null) return 'The last check stopped.'
  const label = failureReasonLabel[reason]
  return `The last check stopped: ${label.charAt(0).toLowerCase()}${label.slice(1)}.`
}

export function scheduleOwnerWords(schedule: ScheduleView): string {
  return `Scheduled checks count as ${schedule.owner_name}’s work, so ${schedule.owner_name} can’t approve them.`
}

/** The ticket keys one row holds: the open one, and the one our version came from. These are the only keys its words may link. */
export function ticketsOf(row: WatchedSoftwareView): string[] {
  return [row.open_ticket, row.our_version_source?.ticket].filter((key): key is string => typeof key === 'string' && key !== '')
}

interface HistoryLine {
  readonly when: string
  readonly words: string
}

/**
 * What the platform has kept about one row. It stores the latest facts, not every earlier check. `declined` is the declined record of the
 * check that found this row's newer version, with what happens next, in the words the row's note gives it.
 */
export function historyOf(row: WatchedSoftwareView, nameOf: (id: string) => string, declined: string | null): HistoryLine[] {
  const now: HistoryLine[] = []
  if (row.open_ticket) now.push({ when: 'Now', words: `${row.open_ticket} is open in Jira for the upgrade.` })
  else if (row.status === 'awaiting_approval') now.push({ when: 'Now', words: 'An upgrade ticket is waiting for a yes.' })
  const dated: { readonly at: string; readonly words: string }[] = []
  const failed = row.status === 'cant_check'
  if (row.checked_at && failed) dated.push({ at: row.checked_at, words: row.problem ? `Couldn’t check. ${row.problem}` : 'Couldn’t check.' })
  const readAt = row.newest_read_at ?? (failed ? null : row.checked_at)
  if (readAt) dated.push({ at: readAt, words: declined && row.newest_version ? `Found ${row.newest_version}. ${declined}` : `Checked. The newest version is ${row.newest_version ?? 'unknown'}.` })
  if (!row.checked_at) now.push({ when: 'Not yet', words: 'Not checked yet.' })
  const source = row.our_version_source
  if (source && row.our_version === null && row.compared_from) {
    dated.push({ at: source.at, words: `Our version is not known. Later checks tell about releases newer than ${row.compared_from}, the newest the first check read.` })
  }
  if (source && row.our_version) {
    const words = source.kind === 'ticket_done' ? `Our version moved to ${row.our_version}. It came from ${source.ticket ?? 'a ticket'}, marked Done.` : `Our version is ${row.our_version}. ${versionSourceWords(source)}.`
    dated.push({ at: source.at, words })
  }
  for (const change of row.address_changes) {
    const who = nameOf(change.by)
    dated.push({ at: change.at, words: change.kind === 'use' ? `${who} used the new address ${change.to_repo}. It was ${change.from_repo}.` : `${who} put the address back to ${change.to_repo}. It was ${change.from_repo}.` })
  }
  dated.push({ at: row.added_at, words: `Added by ${nameOf(row.added_by)}.` })
  const newestFirst = [...dated].sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  return [...now, ...newestFirst.map(({ at, words }) => ({ when: singaporeTime(at), words }))]
}
