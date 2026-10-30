import { ApiError } from '../../api/client'
import { failureReasonLabel } from '../../api/labels'
import type { Day, FailureReason, ScheduleHold, ScheduleView, SoftwareStatus, VersionSourceView, WatchedSoftwareView } from '../../api/types'

export const SOURCES_NOTE =
  'GitHub is the only place we can check today. Other places, such as npm or PyPI, are not available yet.'

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

/** What the schedule does next. The view names no next check while the watchlist is paused or the schedule is held, and paused wins over held. */
export function nextCheckWords(schedule: ScheduleView, paused: boolean): string {
  if (schedule.held && !paused) return heldWords(schedule.held, schedule.owner_name, TAKE_OVER_WORDS)
  return schedule.next_at === null ? PAUSED_WORDS : `Next check ${singaporeTime(schedule.next_at)}, Singapore time.`
}

export function noScheduleWords({ operator, paused }: { readonly operator: boolean; readonly paused: boolean }): string {
  if (paused) return `No schedule. ${PAUSED_WORDS}`
  return operator ? 'No schedule. Press Check now to check by hand.' : 'No schedule. An Operator can press Check now to check by hand.'
}

export function emptyWords({ operator, scheduled, paused }: { readonly operator: boolean } & Checking): string {
  if (!operator) return 'An Operator can add the tools your team runs.'
  if (paused) return 'Add the tools your team runs. They can be checked once an Operator resumes the watchlist.'
  return scheduled ? 'Add the tools your team runs. Each one is checked at the next check.' : 'Add the tools your team runs, then press Check now to check them.'
}

export const statusLabel: Record<SoftwareStatus, string> = {
  cant_check: 'Can’t check',
  behind: 'Behind',
  awaiting_approval: 'Ticket waiting for a yes',
  ticket_open: 'Ticket open',
  up_to_date: 'Up to date',
  not_checked: 'Not checked yet',
}

type StatusTone = 'bad' | 'wait' | 'open' | 'good' | 'quiet'

export const statusTone: Record<SoftwareStatus, StatusTone> = {
  cant_check: 'bad',
  behind: 'wait',
  awaiting_approval: 'wait',
  ticket_open: 'open',
  up_to_date: 'good',
  not_checked: 'quiet',
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
const VERSION = /^\d+\.\d+\.\d+$/
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

export const VERSION_HELP = 'Left empty, the first check takes the newest.'

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

interface Groups {
  readonly needs: readonly WatchedSoftwareView[]
  readonly notChecked: readonly WatchedSoftwareView[]
  readonly upToDate: readonly WatchedSoftwareView[]
}

function matchesQuery(row: WatchedSoftwareView, query: string): boolean {
  const q = query.trim().toLowerCase()
  return q === '' || `${row.name} ${row.source.ref}`.toLowerCase().includes(q)
}

export function groupsOf(rows: readonly WatchedSoftwareView[], query: string): Groups {
  const shown = rows.filter((row) => matchesQuery(row, query))
  return {
    needs: shown.filter((row) => row.status !== 'up_to_date' && row.status !== 'not_checked'),
    notChecked: shown.filter((row) => row.status === 'not_checked'),
    upToDate: shown.filter((row) => row.status === 'up_to_date'),
  }
}

export function countIn(groups: Groups): number {
  return groups.needs.length + groups.notChecked.length + groups.upToDate.length
}

export function versionSourceWords(source: VersionSourceView | null): string {
  if (source === null) return 'Not known until the first check'
  switch (source.kind) {
    case 'given':
      return 'Given when added'
    case 'first_check':
      return 'Taken from the first check'
    case 'ticket_done':
      return source.ticket ? `From ${source.ticket}, marked Done` : 'From a ticket marked Done'
  }
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

const TIME_ZONE = 'Asia/Singapore'
const day = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: TIME_ZONE })
const clock = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone: TIME_ZONE })

/** "Mon 16 Nov, 9:00", in Singapore time. */
export function singaporeTime(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return `${day.format(at).replace(',', '')}, ${clock.format(at).replace(/^0/, '')}`
}

function clockWords(at: string): string {
  return at.replace(/^0/, '')
}

export function repeatWords({ day, at }: { readonly day: Day; readonly at: string }): string {
  return `${dayLabel[day]} at ${clockWords(at)}`
}

/** "Checked every Monday at 9:00, set by Carol." */
export function scheduleWords(schedule: ScheduleView): string {
  return `Checked ${repeatWords(schedule)}, set by ${schedule.owner_name}.`
}

export function stoppedWords(reason: FailureReason | null): string {
  if (reason === null) return 'The last check stopped.'
  const label = failureReasonLabel[reason]
  return `The last check stopped: ${label.charAt(0).toLowerCase()}${label.slice(1)}.`
}

export function scheduleOwnerWords(schedule: ScheduleView): string {
  return `Scheduled checks count as ${schedule.owner_name}’s work, so ${schedule.owner_name} can’t approve them.`
}

interface HistoryLine {
  readonly when: string
  readonly words: string
}

/** What the platform has kept about one row. It stores the latest facts, not every earlier check. */
export function historyOf(row: WatchedSoftwareView, nameOf: (id: string) => string): HistoryLine[] {
  const now: HistoryLine[] = []
  if (row.open_ticket) now.push({ when: 'Now', words: `${row.open_ticket} is open in Jira for the upgrade.` })
  else if (row.status === 'awaiting_approval') now.push({ when: 'Now', words: 'An upgrade ticket is waiting for a yes.' })
  const dated: { readonly at: string; readonly words: string }[] = []
  const failed = row.status === 'cant_check'
  if (row.checked_at && failed) dated.push({ at: row.checked_at, words: row.problem ? `Couldn’t check. ${row.problem}` : 'Couldn’t check.' })
  const readAt = row.newest_read_at ?? (failed ? null : row.checked_at)
  if (readAt) dated.push({ at: readAt, words: `Checked. The newest version is ${row.newest_version ?? 'unknown'}.` })
  if (!row.checked_at) now.push({ when: 'Not yet', words: 'Not checked yet.' })
  const source = row.our_version_source
  if (source && row.our_version) {
    const words = source.kind === 'ticket_done' ? `Our version moved to ${row.our_version}. It came from ${source.ticket ?? 'a ticket'}, marked Done.` : `Our version is ${row.our_version}. ${versionSourceWords(source)}.`
    dated.push({ at: source.at, words })
  }
  dated.push({ at: row.added_at, words: `Added by ${nameOf(row.added_by)}.` })
  const newestFirst = [...dated].sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  return [...now, ...newestFirst.map(({ at, words }) => ({ when: singaporeTime(at), words }))]
}
