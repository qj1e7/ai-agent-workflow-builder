import type {
  ActivityEvent,
  Day,
  DevUser,
  LastCheckView,
  RunState,
  ScheduleView,
  SoftwareStatus,
  UseCaseView,
  VersionSourceView,
  WatchedSoftwareView,
  WatchlistView,
} from '../api/types'
import { fixtures } from './fixtures'
import { isRecord, json, problem } from './http'

// The demo plays the platform's watchlist in the browser: the list, what checks learned, and the schedule.

const ATTENTION: readonly SoftwareStatus[] = [
  'cant_check',
  'behind',
  'awaiting_approval',
  'ticket_open',
  'not_checked',
  'up_to_date',
]
const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/
const VERSION = /^\d+\.\d+\.\d+$/
const CLOCK_TIME = /^([01][0-9]|2[0-3]):[0-5][05]$/
const DAYS: readonly Day[] = ['every_day', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const WEEKDAY: Readonly<Record<Exclude<Day, 'every_day'>, number>> = {
  sunday: 0,
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
}
const SINGAPORE_MS = 8 * 3_600_000
const DAY_MS = 86_400_000
const LIMIT = 100
const OPERATORS_ONLY = 'Only an Operator can do this. Ask an Operator on the team.'
const NO_WATCHLIST = 'Add software first. The watchlist does not exist yet.'
export const NOTHING_TO_CHECK = 'The watchlist is empty, so there is nothing to check.'
const INSTRUCTION =
  "Check the team's watched software for new releases and raise an upgrade ticket for each one that is behind."

interface Listed {
  readonly id: string
  readonly name: string
  readonly ref: string
  /** What the Operator typed when adding, or null. */
  readonly startingVersion: string | null
  readonly addedBy: string
  readonly addedAt: string
}

interface Learned {
  readonly version: string
  readonly source: VersionSourceView
}

interface LatestCheck {
  readonly at: string
  readonly newest: string | null
  readonly problem: string | null
}

interface Schedule {
  readonly day: Day
  readonly at: string
  readonly owner: DevUser
  readonly savedAt: string
}

/** A check's events so far, and what the run says of its approval. */
export interface CheckEvents {
  readonly runId: string
  readonly state: RunState
  readonly startedAt: string
  readonly events: readonly ActivityEvent[]
}

interface Ticket {
  readonly softwareId: string
  readonly version: string
  status: 'proposed' | 'written' | 'dropped'
  approvalId: string | null
  key: string | null
  /** The check's run still waits for an Approver. */
  waiting: boolean
}

interface Facts {
  learned: Learned | null
  latest: LatestCheck | null
  pending: Ticket | null
  open: Ticket | null
}

function isOperator(user: DevUser): boolean {
  return user.roles.includes('operator')
}

function newer(candidate: string, than: string): boolean {
  const left = candidate.split('.')
  const right = than.split('.')
  if (![...left, ...right].every((part) => /^\d+$/.test(part))) return candidate !== than
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const a = Number(left[index] ?? 0)
    const b = Number(right[index] ?? 0)
    if (a !== b) return a > b
  }
  return false
}

/** The next start of a schedule after now, in Singapore time, which has no daylight saving. */
export function nextStart(day: Day, at: string, now: number): string {
  const [hour = 0, minute = 0] = at.split(':').map(Number)
  const local = new Date(now + SINGAPORE_MS)
  const midnight = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - SINGAPORE_MS
  for (let ahead = 0; ahead <= 7; ahead += 1) {
    const start = midnight + ahead * DAY_MS + (hour * 60 + minute) * 60_000
    const weekday = new Date(start + SINGAPORE_MS).getUTCDay()
    if (start > now && (day === 'every_day' || WEEKDAY[day] === weekday)) return new Date(start).toISOString()
  }
  return new Date(now + 7 * DAY_MS).toISOString()
}

function statusOf(facts: Facts, ours: string | null): SoftwareStatus {
  if (facts.latest?.problem) return 'cant_check'
  if (facts.pending) return 'awaiting_approval'
  if (facts.open) return 'ticket_open'
  if (facts.latest?.newest) return ours !== null && newer(facts.latest.newest, ours) ? 'behind' : 'up_to_date'
  return 'not_checked'
}

function resultOf(event: ActivityEvent): { softwareId: string; state: string; newest: string | null } | null {
  if (event.kind !== 'agent_step_finished' || event.data.step !== 'read_source') return null
  const { software_id: softwareId, state, newest } = event.data.result
  if (typeof softwareId !== 'string' || typeof state !== 'string') return null
  return { softwareId, state, newest: typeof newest === 'string' ? newest : null }
}

export interface DoneMark {
  readonly key: string
  readonly at: string
}

export class DemoWatchlist {
  readonly useCaseId: string
  private exists: boolean
  private version: number
  private owner: string
  private readonly ticketProject: string
  private createdAt: string
  private listed: Listed[]
  private readonly learned = new Map<string, Learned>()
  private readonly seeded = new Map<string, LatestCheck>()
  private schedule: Schedule | null
  private counter = 0

  /** The recorded watchlist, moved in time so that its check would start at `start`. */
  constructor(start: number) {
    const before = fixtures.watchlistBeforeCheck
    const offset = start - Date.parse(fixtures.watchlistEvents[0]?.ts ?? new Date(start).toISOString())
    const shift = (iso: string) => new Date(Date.parse(iso) + offset).toISOString()
    this.useCaseId = before.use_case_id
    this.exists = true
    this.version = before.version
    this.ticketProject = before.ticket_project
    this.owner = before.software[0]?.added_by ?? 'alice'
    this.listed = before.software
      .map((row) => ({
        id: row.id,
        name: row.name,
        ref: row.source.ref,
        startingVersion: row.our_version_source?.kind === 'given' ? row.our_version : null,
        addedBy: row.added_by,
        addedAt: shift(row.added_at),
      }))
      .sort((a, b) => Date.parse(a.addedAt) - Date.parse(b.addedAt) || a.id.localeCompare(b.id))
    this.createdAt = this.listed[0]?.addedAt ?? new Date(start).toISOString()
    for (const row of before.software) {
      const source = row.our_version_source
      if (row.our_version && source && source.kind !== 'given') {
        this.learned.set(row.id, { version: row.our_version, source: { ...source, at: shift(source.at) } })
      }
      if (row.checked_at)
        this.seeded.set(row.id, { at: shift(row.checked_at), newest: row.newest_version, problem: row.problem })
    }
    const schedule = before.schedule
    const owner = schedule ? fixtures.devUsers.find((user) => user.id === schedule.owner) : undefined
    this.schedule =
      schedule && owner ? { day: schedule.day, at: schedule.at, owner, savedAt: shift(schedule.saved_at) } : null
  }

  get isEmpty(): boolean {
    return !this.exists || this.listed.length === 0
  }

  useCase(): UseCaseView | null {
    if (!this.exists) return null
    return {
      use_case_id: this.useCaseId,
      version: this.version,
      template: 'software_watchlist',
      name: 'Software watchlist',
      instruction: INSTRUCTION,
      params: { ticket_project: this.ticketProject },
      owner: this.owner,
      created_at: this.createdAt,
      plan: fixtures.templates.find((template) => template.key === 'software_watchlist')?.blocks ?? [],
      agents: [],
    }
  }

  view(checks: readonly CheckEvents[], done: ReadonlyMap<string, string>, wall: number): WatchlistView | null {
    if (!this.exists) return null
    const facts = this.facts(checks, done)
    const rows = this.listed.map((listed) => this.row(listed, facts.get(listed.id)))
    rows.sort(
      (a, b) =>
        ATTENTION.indexOf(a.status) - ATTENTION.indexOf(b.status) ||
        (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1),
    )
    const last = checks.at(-1)
    const lastCheck: LastCheckView | null = last
      ? { run_id: last.runId, state: last.state, started_at: last.startedAt }
      : null
    return {
      use_case_id: this.useCaseId,
      version: this.version,
      ticket_project: this.ticketProject,
      software: rows,
      last_check: lastCheck,
      schedule: this.scheduleView(wall),
    }
  }

  get(checks: readonly CheckEvents[], done: ReadonlyMap<string, string>, wall: number): Response {
    return json(200, { watchlist: this.view(checks, done, wall) })
  }

  add(user: DevUser, body: unknown, wall: number): { response?: Response } {
    if (!isOperator(user)) return { response: problem(403, OPERATORS_ONLY) }
    const parsed = parseAdd(body)
    if ('problems' in parsed) return { response: json(422, { detail: parsed.problems }) }
    const { name, repo, ourVersion } = parsed
    if (this.exists && this.listed.some((listed) => listed.ref.toLowerCase() === repo.toLowerCase())) {
      return { response: problem(409, `${repo} is already watched`) }
    }
    if (this.listed.length >= LIMIT)
      return {
        response: json(422, {
          detail: [{ loc: ['body'], msg: `The watchlist holds ${LIMIT} software at most`, type: 'value_error' }],
        }),
      }
    const at = new Date(wall).toISOString()
    if (!this.exists) {
      this.exists = true
      this.version = 0
      this.owner = user.id
      this.createdAt = at
      this.listed = []
      this.schedule = { day: 'monday', at: '09:00', owner: user, savedAt: at }
    }
    this.counter += 1
    this.listed = [
      ...this.listed,
      { id: `sw_demo${this.counter}`, name, ref: repo, startingVersion: ourVersion, addedBy: user.id, addedAt: at },
    ]
    this.version += 1
    return {}
  }

  remove(user: DevUser, softwareId: string): { response?: Response } {
    if (!isOperator(user)) return { response: problem(403, OPERATORS_ONLY) }
    if (!this.exists || !this.listed.some((listed) => listed.id === softwareId))
      return { response: problem(404, 'No such watched software') }
    this.listed = this.listed.filter((listed) => listed.id !== softwareId)
    this.version += 1
    return {}
  }

  saveSchedule(user: DevUser, body: unknown, wall: number): { response?: Response } {
    if (!isOperator(user)) return { response: problem(403, OPERATORS_ONLY) }
    if (!this.exists) return { response: problem(404, NO_WATCHLIST) }
    const day = isRecord(body) ? body['day'] : undefined
    const at = isRecord(body) ? body['at'] : undefined
    const problems = [
      ...(typeof day === 'string' && (DAYS as readonly string[]).includes(day)
        ? []
        : [{ loc: ['body', 'day'], msg: 'Input should be a day', type: 'enum' }]),
      ...(typeof at === 'string' && CLOCK_TIME.test(at)
        ? []
        : [{ loc: ['body', 'at'], msg: 'String should match pattern', type: 'string_pattern_mismatch' }]),
    ]
    if (problems.length > 0) return { response: json(422, { detail: problems }) }
    this.schedule = { day: day as Day, at: at as string, owner: user, savedAt: new Date(wall).toISOString() }
    return {}
  }

  turnOffSchedule(user: DevUser): { response?: Response } {
    if (!isOperator(user)) return { response: problem(403, OPERATORS_ONLY) }
    if (!this.exists) return { response: problem(404, NO_WATCHLIST) }
    this.schedule = null
    return {}
  }

  private scheduleView(wall: number): ScheduleView | null {
    const schedule = this.schedule
    if (!schedule) return null
    return {
      day: schedule.day,
      at: schedule.at,
      time_zone: 'Asia/Singapore',
      owner: schedule.owner.id,
      owner_name: schedule.owner.display,
      saved_at: schedule.savedAt,
      next_at: nextStart(schedule.day, schedule.at, wall),
    }
  }

  private row(listed: Listed, facts: Facts | undefined): WatchedSoftwareView {
    const learned = this.learned.get(listed.id)
    const known = facts?.learned ?? learned ?? null
    const given: Learned | null = listed.startingVersion
      ? { version: listed.startingVersion, source: { kind: 'given', at: listed.addedAt, ticket: null } }
      : null
    const ours = known ?? given
    const all: Facts = facts ?? { learned: null, latest: this.seeded.get(listed.id) ?? null, pending: null, open: null }
    return {
      id: listed.id,
      name: listed.name,
      source: { kind: 'github', ref: listed.ref, url: `https://github.com/${listed.ref}/releases` },
      our_version: ours?.version ?? null,
      our_version_source: ours?.source ?? null,
      newest_version: all.latest?.newest ?? null,
      checked_at: all.latest?.at ?? null,
      status: statusOf(all, ours?.version ?? null),
      problem: all.latest?.problem ?? null,
      open_ticket: all.open?.key ?? null,
      approval_id: all.pending?.approvalId ?? null,
      added_by: listed.addedBy,
      added_at: listed.addedAt,
    }
  }

  /** What every check so far taught the platform, then the tickets marked Done. Mirrors the platform's lifecycle hooks. */
  private facts(checks: readonly CheckEvents[], done: ReadonlyMap<string, string>): Map<string, Facts> {
    const facts = new Map<string, Facts>()
    const of = (softwareId: string): Facts => {
      let found = facts.get(softwareId)
      if (!found) {
        found = {
          learned: this.learned.get(softwareId) ?? null,
          latest: this.seeded.get(softwareId) ?? null,
          pending: null,
          open: null,
        }
        facts.set(softwareId, found)
      }
      return found
    }
    const tickets: Ticket[] = []
    for (const check of checks) {
      let behind: { softwareId: string; version: string }[] = []
      let proposed: Ticket[] = []
      let written = 0
      for (const event of check.events) {
        const result = resultOf(event)
        if (result) {
          const fact = of(result.softwareId)
          if (result.state === 'cant_check') {
            // The recording carries no problem sentence, so a source that still cannot be read keeps the one it had.
            fact.latest = {
              at: event.ts,
              newest: null,
              problem: fact.latest?.problem ?? 'The source could not be read.',
            }
          } else {
            fact.latest = { at: event.ts, newest: result.newest, problem: null }
          }
          const starting = this.listed.find((listed) => listed.id === result.softwareId)?.startingVersion ?? null
          if (result.state === 'starting_point' && result.newest && !fact.learned && starting === null) {
            fact.learned = { version: result.newest, source: { kind: 'first_check', at: event.ts, ticket: null } }
          }
          if (result.state === 'behind' && result.newest)
            behind.push({ softwareId: result.softwareId, version: result.newest })
        } else if (event.kind === 'write_action_proposed') {
          proposed = behind.map((item) => ({
            ...item,
            status: 'proposed',
            approvalId: null,
            key: null,
            waiting: false,
          }))
          tickets.push(...proposed)
          written = 0
        } else if (event.kind === 'approval_requested') {
          for (const ticket of proposed) ticket.approvalId = event.data.approval_id
        } else if (event.kind === 'write_action_done') {
          const ticket = proposed[written]
          written += 1
          if (ticket) {
            ticket.status = 'written'
            ticket.key = event.data.external_reference
          }
        } else if (event.kind === 'run_rejected' || event.kind === 'run_failed' || event.kind === 'run_retried') {
          for (const ticket of proposed) if (ticket.status === 'proposed') ticket.status = 'dropped'
          if (event.kind === 'run_retried') behind = []
        }
      }
      for (const ticket of proposed) ticket.waiting = check.state === 'awaiting_approval'
    }
    for (const ticket of tickets) {
      const fact = of(ticket.softwareId)
      if (ticket.status === 'proposed' && ticket.waiting && ticket.approvalId) fact.pending = ticket
      if (ticket.status !== 'written' || !ticket.key) continue
      const doneAt = done.get(ticket.key)
      if (doneAt) {
        fact.learned = { version: ticket.version, source: { kind: 'ticket_done', at: doneAt, ticket: ticket.key } }
        if (fact.open === ticket) fact.open = null
      } else {
        fact.open = ticket
      }
    }
    return facts
  }
}

type Parsed =
  | { name: string; repo: string; ourVersion: string | null }
  | { problems: { loc: string[]; msg: string; type: string }[] }

function parseAdd(body: unknown): Parsed {
  const record = isRecord(body) ? body : {}
  const name = typeof record['name'] === 'string' ? record['name'].trim() : ''
  const repo = typeof record['repo'] === 'string' ? record['repo'] : ''
  const version = record['our_version']
  const problems = [
    ...(name.length >= 1 && name.length <= 80
      ? []
      : [{ loc: ['body', 'name'], msg: 'String should have 1 to 80 characters', type: 'string_too_short' }]),
    ...(REPO.test(repo)
      ? []
      : [{ loc: ['body', 'repo'], msg: 'String should match pattern', type: 'string_pattern_mismatch' }]),
    ...(version === undefined || version === null || (typeof version === 'string' && VERSION.test(version))
      ? []
      : [{ loc: ['body', 'our_version'], msg: 'String should match pattern', type: 'string_pattern_mismatch' }]),
  ]
  if (problems.length > 0) return { problems }
  return { name, repo, ourVersion: typeof version === 'string' ? version : null }
}
