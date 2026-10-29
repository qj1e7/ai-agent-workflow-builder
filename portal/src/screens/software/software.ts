import type { Day, ScheduleView, SoftwareStatus, VersionSourceView, WatchedSoftwareView } from '../../api/types'

export const SOURCES_NOTE =
  'GitHub is the only place we can check today. Other places, such as npm or PyPI, are not available yet.'

export const CANT_CHECK_WORDS = 'Can’t check right now. It will try again at the next check.'

export const statusLabel: Record<SoftwareStatus, string> = {
  cant_check: 'Can’t check',
  behind: 'Behind',
  awaiting_approval: 'Ticket waiting for a yes',
  ticket_open: 'Ticket open',
  up_to_date: 'Up to date',
  not_checked: 'Not checked yet',
}

export type StatusTone = 'bad' | 'wait' | 'open' | 'good' | 'quiet'

export const statusTone: Record<SoftwareStatus, StatusTone> = {
  cant_check: 'bad',
  behind: 'wait',
  awaiting_approval: 'wait',
  ticket_open: 'open',
  up_to_date: 'good',
  not_checked: 'quiet',
}

export const dayLabel: Record<Day, string> = {
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
const VERSION = /^\d+\.\d+\.\d+$/
const CLOCK = /^([01][0-9]|2[0-3]):[0-5][05]$/
const NAME_LIMIT = 80

export const REPO_HELP = 'Paste the project’s GitHub link, or type owner/name.'
export const REPO_BAD = 'That doesn’t look like a GitHub project. Paste its GitHub link, or type owner/name.'
export const REPO_EMPTY = `Type its GitHub repository. ${REPO_HELP}`

export type Checked<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly words: string }

/** A pasted GitHub link or owner/name, as the owner/name the platform wants. */
export function repoOf(text: string): string {
  const trimmed = text.trim()
  const link = /github\.com\/([^/\s]+\/[^/\s#?]+)/i.exec(trimmed)
  return (link?.[1] ?? trimmed).replace(/\.git$/i, '').replace(/\/$/, '')
}

export function checkRepo(text: string, watched: readonly string[] = []): Checked<string> {
  const repo = repoOf(text)
  if (repo === '') return { ok: false, words: REPO_EMPTY }
  if (!REPO.test(repo)) return { ok: false, words: REPO_BAD }
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

export function checkVersion(text: string): Checked<string | null> {
  const version = text.trim()
  if (version === '') return { ok: true, value: null }
  if (!VERSION.test(version)) return { ok: false, words: 'Type the version as three numbers, such as 1.2.14.' }
  return { ok: true, value: version }
}

export function checkClock(text: string): Checked<string> {
  const at = text.trim()
  return CLOCK.test(at) ? { ok: true, value: at } : { ok: false, words: 'Pick a time on a 5-minute step, such as 9:00.' }
}

export function matches(count: number): string {
  if (count === 0) return 'No matches'
  return count === 1 ? '1 match' : `${count} matches`
}

export function itemsCount(count: number): string {
  return count === 1 ? '1 item' : `${count} items`
}

export interface Groups {
  readonly needs: readonly WatchedSoftwareView[]
  readonly notChecked: readonly WatchedSoftwareView[]
  readonly upToDate: readonly WatchedSoftwareView[]
}

export function matchesQuery(row: WatchedSoftwareView, query: string): boolean {
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

export function clockWords(at: string): string {
  return at.replace(/^0/, '')
}

/** "Checked every Monday at 9:00, set by Carol." */
export function scheduleWords(schedule: ScheduleView): string {
  return `Checked ${dayLabel[schedule.day]} at ${clockWords(schedule.at)}, set by ${schedule.owner_name}.`
}

export function scheduleOwnerWords(schedule: ScheduleView): string {
  return `Scheduled checks count as ${schedule.owner_name}’s work, so ${schedule.owner_name} can’t approve them.`
}

export interface HistoryLine {
  readonly when: string
  readonly words: string
}

/** What the platform has kept about one row. It stores the latest facts, not every earlier check. */
export function historyOf(row: WatchedSoftwareView, nameOf: (id: string) => string): HistoryLine[] {
  const lines: HistoryLine[] = []
  if (row.open_ticket) lines.push({ when: 'Now', words: `${row.open_ticket} is open in Jira for the upgrade.` })
  else if (row.status === 'awaiting_approval') lines.push({ when: 'Now', words: 'An upgrade ticket is waiting for a yes.' })
  if (row.checked_at) {
    lines.push({
      when: singaporeTime(row.checked_at),
      words: row.status === 'cant_check' ? (row.problem ? `Couldn’t check. ${row.problem}` : 'Couldn’t check.') : `Checked. The newest version is ${row.newest_version ?? 'unknown'}.`,
    })
  } else {
    lines.push({ when: 'Not yet', words: 'Not checked yet.' })
  }
  const source = row.our_version_source
  if (source && row.our_version) {
    const where = source.kind === 'ticket_done' ? `Our version moved to ${row.our_version}. It came from ${source.ticket ?? 'a ticket'}, marked Done.` : `Our version is ${row.our_version}. ${versionSourceWords(source)}.`
    lines.push({ when: singaporeTime(source.at), words: where })
  }
  lines.push({ when: singaporeTime(row.added_at), words: `Added by ${nameOf(row.added_by)}.` })
  return lines
}
