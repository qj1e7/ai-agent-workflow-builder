/**
 * The Portal's time words. Every time is Singapore time unless it names its zone. A schedule's next run is shown in the schedule's own zone,
 * and names it when that is not Singapore. This module imports no screen, so the Workflows and Software pages can both use it.
 */

const TIME_ZONE = 'Asia/Singapore'
/** Where the formatters are built, so a test can count the builds. */
export const formatterFactory = {
  build: (timeZone: string) =>
    new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone }),
}

interface Zone {
  readonly formatter: Intl.DateTimeFormat
  /** False when the browser cannot read the name. Its times are then Singapore's, and say so. */
  readonly known: boolean
}

const zones = new Map<string, Zone>()

/** Built once per zone name, the unreadable ones included. */
function zoneOf(name: string): Zone {
  let zone = zones.get(name)
  if (!zone) {
    try {
      zone = { formatter: formatterFactory.build(name), known: true }
    } catch {
      zone = { formatter: name === TIME_ZONE ? formatterFactory.build(TIME_ZONE) : zoneOf(TIME_ZONE).formatter, known: false }
    }
    zones.set(name, zone)
  }
  return zone
}

const partsIn = (name: string) => zoneOf(name).formatter

interface Moment {
  readonly weekday: string
  readonly day: string
  readonly month: string
  readonly year: string
  readonly clock: string
}

function momentOf(at: Date, zone = TIME_ZONE): Moment {
  const all = partsIn(zone).formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => all.find((p) => p.type === type)?.value ?? ''
  return { weekday: part('weekday'), day: part('day'), month: part('month'), year: part('year'), clock: `${Number(part('hour'))}:${part('minute')}` }
}

function dayWords(at: Moment, now: Moment): string {
  const date = `${at.weekday} ${at.day} ${at.month}`
  return at.year === now.year ? date : `${date} ${at.year}`
}

const sameDay = (a: Moment, b: Moment) => a.day === b.day && a.month === b.month && a.year === b.year

/** "Today, 10:14", "Tue 3 Nov, 10:14" or "Mon 4 Jan 2027, 9:00", in Singapore time unless a schedule names another zone. */
export function runWhen(iso: string, now: Date, zone = TIME_ZONE): string {
  const at = momentOf(new Date(iso), zone)
  const today = momentOf(now, zone)
  return `${sameDay(at, today) ? 'Today' : dayWords(at, today)}, ${at.clock}`
}

/** "Mon 23 Nov, 9:00", the Software page's form, which never says Today. In the zone, or in Singapore when the browser cannot read it. */
export function dateAndClock(iso: string, zone = TIME_ZONE): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const moment = momentOf(at, zone)
  return `${moment.weekday} ${moment.day} ${moment.month}, ${moment.clock}`
}

/** The list's shorter form: "Today 10:14", or the date alone. */
export function lineWhen(iso: string, now: Date): string {
  const at = momentOf(new Date(iso))
  const today = momentOf(now)
  return sameDay(at, today) ? `Today ${at.clock}` : dayWords(at, today)
}

/** A blank zone means the platform named none, so its times are Singapore's. */
const isSingapore = (zone: string | undefined) => !zone || zone === TIME_ZONE

const SINGAPORE_TIME = 'Singapore time'

/** The zone a schedule's times are shown in: its own when the browser can read it, otherwise Singapore. "London time", "UTC" or "Singapore time". */
export function timesZone(zone: string | undefined): string {
  if (!zone || isSingapore(zone) || !zoneOf(zone).known) return SINGAPORE_TIME
  return zoneName(zone)
}

/**
 * A next run, in the schedule's own zone, with that zone named after it unless it is Singapore, as every other time in the Portal is.
 * The same next run reads the same on every page: "Today, 9:00 London time", or "Today, 17:00 Singapore time" for a zone the browser cannot read.
 */
export function nextRunAt(iso: string, now: Date, zone?: string): string {
  const when = runWhen(iso, now, zone)
  return isSingapore(zone) ? when : `${when} ${timesZone(zone)}`
}

const UTC_NAMES = new Set(['UTC', 'Etc/UTC', 'GMT', 'Etc/GMT', 'GMT0', 'Etc/GMT0', 'GMT+0', 'GMT-0', 'Etc/UCT', 'UCT', 'Universal', 'Etc/Universal', 'Zulu', 'Etc/Zulu', 'Greenwich', 'Etc/Greenwich'])

/**
 * Built from the zone's id alone, without Intl, so a zone the browser cannot read is still named for what it is. Singapore keeps its short name.
 * A real Area/City zone is named by its city, as in "London time". The fixed Etc/GMT+N zones get their offset, whose sign is the other way round.
 * Any other zone shows its id, because today's offset can be wrong on the run's date.
 */
function zoneName(name: string): string {
  if (isSingapore(name)) return 'Singapore time (SGT)'
  if (UTC_NAMES.has(name)) return 'UTC'
  const fixed = /^Etc\/GMT([+-])(\d+)$/.exec(name)
  if (fixed) {
    const hours = Number(fixed[2])
    return hours === 0 ? 'UTC' : `GMT${fixed[1] === '+' ? '-' : '+'}${hours}`
  }
  const city = /^(?!Etc\/)[A-Z][A-Za-z]+\/(?:[A-Za-z_-]+\/)?([A-Z][A-Za-z_-]+)$/.exec(name)?.[1]
  return city ? `${city.replaceAll(/[_-]/g, ' ')} time` : `${name} time`
}

/** The schedule's own zone, as When gives it: "London time.", "UTC." or "Singapore time (SGT)." */
export const zoneWords = (name: string) => `${zoneName(name)}.`

/** The schedule's own zone, named after its clock time, or null for Singapore: "at 9:00 London time". Built from the id, so it names a zone the browser cannot read too. */
export function scheduleZoneName(zone: string | undefined): string | null {
  return !zone || isSingapore(zone) ? null : zoneName(zone)
}
