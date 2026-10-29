import { ApiError } from '../../api/client'
import type { Day, ScheduleView, SoftwareStatus, VersionSourceView, WatchedSoftwareView } from '../../api/types'

export const SOURCES_NOTE =
  'GitHub is the only place we can check today. Other places, such as npm or PyPI, are not available yet.'

export function cantCheckWords(scheduled: boolean): string {
  return scheduled ? 'Can’t check right now. It will try again at the next check.' : 'Can’t check right now. With no schedule, it is checked again when an Operator presses Check now.'
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
  monday: 'every Monday',
  tuesday: 'every Tuesday',
  wednesday: 'every Wednesday',
  thursday: 'every Thursday',
  friday: 'every Friday',
  saturday: 'every Saturday',
  sunday: 'every Sunday',
}

export const DAYS: readonly Day[] = ['every_day', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

export const dayOption: Record<Day, string> = {
  every_day: 'Every day',
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
}

const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/
/** The platform refuses a name of . or .., which GitHub would read as a path. */
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

/** The platform's 422 on an add, as words beside each field. A problem with no field is the full list. */
export function addProblems(error: unknown): FormErrors | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null
  const detail = (error.body as { detail?: unknown } | null)?.detail
  if (!Array.isArray(detail)) return null
  const found: Partial<Record<keyof FormErrors, string>> = {}
  for (const problem of detail as { loc?: unknown }[]) {
    const loc = Array.isArray(problem.loc) ? problem.loc : []
    const field = loc.length === 1 ? 'form' : REFUSED_FIELD[String(loc.at(-1))]
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

/** "Checked every Monday at 9:00, set by Carol." */
export function scheduleWords(schedule: ScheduleView): string {
  return `Checked ${dayLabel[schedule.day]} at ${clockWords(schedule.at)}, set by ${schedule.owner_name}.`
}

/** "The last check stopped: an agent could not finish its work." The reason is one of the run page's labels. */
export function stoppedWords(reason: string | null): string {
  return reason ? `The last check stopped: ${reason.charAt(0).toLowerCase()}${reason.slice(1)}.` : 'The last check stopped.'
}

export function scheduleOwnerWords(schedule: ScheduleView): string {
  return `Scheduled checks count as ${schedule.owner_name}’s work, so ${schedule.owner_name} can’t approve them.`
}

interface HistoryLine {
  readonly when: string
  readonly words: string
}

/** What the platform has kept about one row, newest first. It stores the latest facts, not every earlier check. */
export function historyOf(row: WatchedSoftwareView, nameOf: (id: string) => string): HistoryLine[] {
  const now: HistoryLine[] = []
  if (row.open_ticket) now.push({ when: 'Now', words: `${row.open_ticket} is open in Jira for the upgrade.` })
  else if (row.status === 'awaiting_approval') now.push({ when: 'Now', words: 'An upgrade ticket is waiting for a yes.' })
  const dated: { readonly at: string; readonly words: string }[] = []
  if (row.checked_at) {
    const failed = row.status === 'cant_check'
    dated.push({ at: row.checked_at, words: failed ? (row.problem ? `Couldn’t check. ${row.problem}` : 'Couldn’t check.') : `Checked. The newest version is ${row.newest_version ?? 'unknown'}.` })
  } else {
    now.push({ when: 'Not yet', words: 'Not checked yet.' })
  }
  const source = row.our_version_source
  if (source && row.our_version) {
    const words = source.kind === 'ticket_done' ? `Our version moved to ${row.our_version}. It came from ${source.ticket ?? 'a ticket'}, marked Done.` : `Our version is ${row.our_version}. ${versionSourceWords(source)}.`
    dated.push({ at: source.at, words })
  }
  dated.push({ at: row.added_at, words: `Added by ${nameOf(row.added_by)}.` })
  const newestFirst = [...dated].sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  return [...now, ...newestFirst.map(({ at, words }) => ({ when: singaporeTime(at), words }))]
}
