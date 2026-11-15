/**
 * The Portal's time words. Every time is in the team time zone unless it names its zone. /api/v1/me names the team time zone, and it is
 * Singapore until it has. A schedule's next run is shown in the schedule's own zone, and names it when that is not the team's.
 * This module imports no screen, so the Workflows and Software pages and the shell can all use it.
 */

const SINGAPORE = 'Asia/Singapore'
let team = SINGAPORE

/** Where the formatters are built, so a test can count the builds. */
export const formatterFactory = {
  build: (timeZone: string) =>
    new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone }),
}

/** The formatter for a zone the browser can read, else null. */
const zones = new Map<string, Intl.DateTimeFormat | null>()

/** Built once per zone name, the unreadable ones included. */
function formatterOf(name: string): Intl.DateTimeFormat | null {
  if (!zones.has(name)) {
    try {
      zones.set(name, formatterFactory.build(name))
    } catch {
      zones.set(name, null)
    }
  }
  return zones.get(name) ?? null
}

const known = (name: string) => formatterOf(name) !== null

/** Takes /api/v1/me's zone. A blank one, or one the browser cannot read, leaves Singapore, so every time still says the zone it is in. */
export function setTeamZone(zone: string | undefined): void {
  team = zone && known(zone) ? zone : SINGAPORE
}

export const teamZone = (): string => team

/** A formatter with these options in the team time zone, built again only when the zone changes. */
export function inTeamZone(options: Omit<Intl.DateTimeFormatOptions, 'timeZone'>): () => Intl.DateTimeFormat {
  let built: { readonly zone: string; readonly formatter: Intl.DateTimeFormat } | null = null
  return () => {
    if (built?.zone !== team) built = { zone: team, formatter: new Intl.DateTimeFormat('en-GB', { ...options, timeZone: team }) }
    return built.formatter
  }
}

/** A zone the browser cannot read gives its times in the team time zone, and says so. */
function partsIn(name: string): Intl.DateTimeFormat {
  const formatter = formatterOf(name) ?? formatterOf(team)
  if (formatter === null) throw new RangeError(`The browser cannot read the team time zone, ${team}.`)
  return formatter
}

interface Moment {
  readonly weekday: string
  readonly day: string
  readonly month: string
  readonly year: string
  readonly clock: string
}

function momentOf(at: Date, zone = team): Moment {
  const all = partsIn(zone).formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => all.find((p) => p.type === type)?.value ?? ''
  return { weekday: part('weekday'), day: part('day'), month: part('month'), year: part('year'), clock: `${Number(part('hour'))}:${part('minute')}` }
}

function dayWords(at: Moment, now: Moment): string {
  const date = `${at.weekday} ${at.day} ${at.month}`
  return at.year === now.year ? date : `${date} ${at.year}`
}

const sameDay = (a: Moment, b: Moment) => a.day === b.day && a.month === b.month && a.year === b.year

/** "Today, 10:14", "Tue 3 Nov, 10:14" or "Mon 4 Jan 2027, 9:00", in the team time zone unless a schedule names another zone. */
export function runWhen(iso: string, now: Date, zone = team): string {
  const at = momentOf(new Date(iso), zone)
  const today = momentOf(now, zone)
  return `${sameDay(at, today) ? 'Today' : dayWords(at, today)}, ${at.clock}`
}

const WEEKDAYS: Readonly<Record<string, string>> = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday' }
const DAY_MS = 86_400_000

/**
 * A first run as the set-up card says it, after "First run": "today, 9:00", "tomorrow, 9:00", "Monday, 9:00" within the week, else
 * "Fri 20 Nov, 9:00". In the schedule's zone, as every next run is.
 */
export function firstRunWhen(iso: string, now: Date, zone = team): string {
  const at = new Date(iso)
  const moment = momentOf(at, zone)
  const today = momentOf(now, zone)
  if (sameDay(moment, today)) return `today, ${moment.clock}`
  if (sameDay(moment, momentOf(new Date(now.getTime() + DAY_MS), zone))) return `tomorrow, ${moment.clock}`
  if (at.getTime() - now.getTime() < 6 * DAY_MS) return `${WEEKDAYS[moment.weekday] ?? moment.weekday}, ${moment.clock}`
  return `${dayWords(moment, today)}, ${moment.clock}`
}

/** "Mon 23 Nov, 9:00", the Software page's form, which never says Today. In the zone, or in the team's when the browser cannot read it. */
export function dateAndClock(iso: string, zone = team): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const moment = momentOf(at, zone)
  return `${moment.weekday} ${moment.day} ${moment.month}, ${moment.clock}`
}

/** When a version was made, after "published by Alice": "just now" within the minute, "today, 9:10", or "Tue 3 Nov, 9:10". */
export function publishedWhen(iso: string, now: Date): string {
  const at = new Date(iso)
  if (now.getTime() - at.getTime() < 60_000) return 'just now'
  const moment = momentOf(at)
  const today = momentOf(now)
  return `${sameDay(moment, today) ? 'today' : dayWords(moment, today)}, ${moment.clock}`
}

/** When a hold began, after "since": "9:10" on the same day, else "Tue 3 Nov, 9:10". */
export function sinceWhen(iso: string, now: Date): string {
  const moment = momentOf(new Date(iso))
  const today = momentOf(now)
  return sameDay(moment, today) ? moment.clock : `${dayWords(moment, today)}, ${moment.clock}`
}

/** The list's shorter form: "Today 10:14", or the date alone. */
export function lineWhen(iso: string, now: Date): string {
  const at = momentOf(new Date(iso))
  const today = momentOf(now)
  return sameDay(at, today) ? `Today ${at.clock}` : dayWords(at, today)
}

/** A blank zone means the platform named none, so its times are the team's. */
const isTeams = (zone: string | undefined) => !zone || zone === team

/** "Singapore time", "London time" or "UTC": the zone of every time that names none. */
export const teamTime = (): string => timeName(team)

/** "Singapore", "London" or "UTC", as a time field's label names it. */
export const teamPlace = (): string => placeName(team)

/** The zone a schedule's times are shown in: its own when the browser can read it, otherwise the team's. "London time", "UTC" or "Singapore time". */
export function timesZone(zone: string | undefined): string {
  return zone && !isTeams(zone) && known(zone) ? timeName(zone) : teamTime()
}

/**
 * A next run, in the schedule's own zone, with that zone named after it unless it is the team's, as every other time in the Portal is.
 * The same next run reads the same on every page: "Today, 9:00 London time", or "Today, 17:00 Singapore time" for a zone the browser cannot read.
 */
export function nextRunAt(iso: string, now: Date, zone?: string): string {
  const when = runWhen(iso, now, zone)
  return isTeams(zone) ? when : `${when} ${timesZone(zone)}`
}

const UTC_NAMES = new Set(['UTC', 'Etc/UTC', 'GMT', 'Etc/GMT', 'GMT0', 'Etc/GMT0', 'GMT+0', 'GMT-0', 'Etc/UCT', 'UCT', 'Universal', 'Etc/Universal', 'Zulu', 'Etc/Zulu', 'Greenwich', 'Etc/Greenwich'])

/**
 * Built from the zone's id alone, without Intl, so a zone the browser cannot read is still named for what it is.
 * A real Area/City zone is named by its city, as in "London". The fixed Etc/GMT+N zones get their offset, whose sign is the other way round.
 * Any other zone shows its id, because today's offset can be wrong on the run's date.
 */
function placeName(name: string): string {
  if (UTC_NAMES.has(name)) return 'UTC'
  const fixed = /^Etc\/GMT([+-])(\d+)$/.exec(name)
  if (fixed) {
    const hours = Number(fixed[2])
    return hours === 0 ? 'UTC' : `GMT${fixed[1] === '+' ? '-' : '+'}${hours}`
  }
  const city = /^(?!Etc\/)[A-Z][A-Za-z]+\/(?:[A-Za-z_-]+\/)?([A-Z][A-Za-z_-]+)$/.exec(name)?.[1]
  return city ? city.replaceAll(/[_-]/g, ' ') : name
}

const isOffset = (name: string) => UTC_NAMES.has(name) || /^Etc\/GMT[+-]\d+$/.test(name)

/** "London time", or the offset alone for UTC and a fixed offset: "UTC", "GMT+8". */
function timeName(name: string): string {
  return isOffset(name) ? placeName(name) : `${placeName(name)} time`
}

/** The schedule's own zone, as When gives it: "London time.", "UTC." or "Singapore time (SGT).". A blank one is the team's. */
export function zoneWords(name: string): string {
  const zone = name || team
  return zone === SINGAPORE ? 'Singapore time (SGT).' : `${timeName(zone)}.`
}

/** The schedule's own zone, named after its clock time, or null for the team's: "at 9:00 London time". Built from the id, so it names a zone the browser cannot read too. */
export function scheduleZoneName(zone: string | undefined): string | null {
  return zone && !isTeams(zone) ? timeName(zone) : null
}
