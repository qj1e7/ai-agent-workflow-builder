import capabilitiesFixture from '@contracts/fixtures/planner/capabilities.json'
import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { CapabilityView, ScheduleView, SoftwareStatus, WatchedSoftwareView } from '../../api/types'
import {
  addProblems,
  cantCheckWords,
  checkClock,
  checkedOnWords,
  checkName,
  checkRepo,
  checkVersion,
  countLine,
  DAYS,
  dayOption,
  decisionsOf,
  decisionTitle,
  emptyWords,
  historyOf,
  matches,
  newestOf,
  nextCheckOf,
  nextCheckWords,
  noScheduleWords,
  oursOf,
  repoOf,
  rowsMatching,
  scheduleOwnerWords,
  scheduleRuns,
  scheduleWords,
  singaporeTime,
  statusLabel,
  statusWords,
  versionSourceWords,
  waitingWords,
  watchAttention,
} from './software'
import { formatterFactory, nextRunWords } from '../workflows/workflow'

const ROWS = statuses.software as WatchedSoftwareView[]
const SCHEDULE = statuses.schedule as ScheduleView
const nameOf = (id: string) => (id === 'alice' ? 'Alice' : id)

describe('the GitHub reference check', () => {
  it('takes owner/name as typed', () => {
    expect(checkRepo('fastapi/fastapi')).toEqual({ ok: true, value: 'fastapi/fastapi' })
  })

  it('takes a pasted link, with a trailing slash, .git or a page after it', () => {
    expect(repoOf('https://github.com/langchain-ai/langgraph/')).toBe('langchain-ai/langgraph')
    expect(repoOf('https://github.com/langchain-ai/langgraph.git')).toBe('langchain-ai/langgraph')
    expect(repoOf('github.com/redis/redis/releases?x=1')).toBe('redis/redis')
  })

  it('says what is wrong for each badly formed reference and accepts none of them', () => {
    for (const bad of ['fastapi', 'fastapi/', '/fastapi', 'a b/c', 'https://example.com/a/b', '-x/y', 'a/b/c', 'owner/..', 'owner/.', 'https://github.com/owner/..']) {
      const checked = checkRepo(bad)
      expect(checked.ok, bad).toBe(false)
      if (!checked.ok) expect(checked.words).toMatch(/GitHub/)
    }
  })

  it('asks for a reference when the field is empty', () => {
    const checked = checkRepo('  ')
    expect(checked.ok).toBe(false)
    if (!checked.ok) expect(checked.words).toMatch(/^Type its GitHub repository/)
  })

  it('refuses a repository that is already watched, whatever its case', () => {
    const checked = checkRepo('FastAPI/FastAPI', ['fastapi/fastapi'])
    expect(checked).toEqual({ ok: false, words: 'FastAPI/FastAPI is already on the list.' })
  })
})

describe('what the platform refused when adding', () => {
  const refused = (...loc: string[][]) => new ApiError(422, { detail: loc.map((where) => ({ loc: where, msg: 'refused', type: 'value_error' })) })

  it('puts each field the platform refused beside that field, in plain words', () => {
    expect(addProblems(refused(['body', 'name']))).toEqual({ name: 'Give the software a name of 80 letters or fewer.' })
    expect(addProblems(refused(['body', 'repo']))).toEqual({ repo: 'That doesn’t look like a GitHub project. Paste its GitHub link, or type owner/name.' })
    expect(addProblems(refused(['body', 'our_version'], ['body', 'name']))).toEqual({
      version: 'Type the version as three numbers, such as 1.2.14.',
      name: 'Give the software a name of 80 letters or fewer.',
    })
  })

  it('says the list is full when the platform refused the whole add', () => {
    const full = new ApiError(422, { detail: [{ type: 'watchlist_full', loc: ['body'], msg: 'The watchlist holds 100 software at most' }] })
    expect(addProblems(full)).toEqual({ form: 'The list is full. Remove software you no longer run, then add this one.' })
    expect(addProblems(new ApiError(422, { detail: [{ type: 'missing', loc: ['body'], msg: 'Field required' }] }))).toBeNull()
  })

  it('leaves any other answer to the general words', () => {
    expect(addProblems(new ApiError(409, { detail: 'langchain-ai/langgraph is already watched' }))).toBeNull()
    expect(addProblems(new ApiError(422, { detail: 'not a list' }))).toBeNull()
    expect(addProblems(new Error('offline'))).toBeNull()
  })
})

describe('the other field checks', () => {
  it('needs a name that is new and short enough', () => {
    expect(checkName('')).toEqual({ ok: false, words: 'Give the software a name.' })
    expect(checkName('redis', ['Redis'])).toEqual({ ok: false, words: 'redis is already on the list.' })
    expect(checkName('x'.repeat(81)).ok).toBe(false)
    expect(checkName('  Redis ')).toEqual({ ok: true, value: 'Redis' })
  })

  it('lets our version stay empty and wants three numbers otherwise, with or without a v', () => {
    expect(checkVersion('')).toEqual({ ok: true, value: null })
    expect(checkVersion('1.2.14')).toEqual({ ok: true, value: '1.2.14' })
    expect(checkVersion('v2.0.0')).toEqual({ ok: true, value: 'v2.0.0' })
    for (const bad of ['1.2', 'v1.2', 'vv1.2.3', '1.2.x', '1.2.3-beta']) expect(checkVersion(bad).ok, bad).toBe(false)
  })

  it('takes a time on a 5-minute step', () => {
    expect(checkClock('09:00').ok).toBe(true)
    expect(checkClock('09:05').ok).toBe(true)
    expect(checkClock('09:03').ok).toBe(false)
    expect(checkClock('').ok).toBe(false)
  })
})

describe('status labels', () => {
  it('has plain words for every status the platform sends', () => {
    expect(statusLabel).toEqual({
      cant_check: 'Can’t check',
      behind: 'New version',
      awaiting_approval: 'Ticket waiting for a yes',
      ticket_open: 'Ticket open',
      up_to_date: 'Up to date',
      not_checked: 'Not checked yet',
    })
  })

  it('says where our version came from', () => {
    expect(versionSourceWords({ kind: 'given', at: '2026-11-02T10:00:00Z', ticket: null })).toBe('Given when added')
    expect(versionSourceWords({ kind: 'first_check', at: '2026-11-02T10:00:00Z', ticket: null })).toBe('Compared from the first check')
    expect(versionSourceWords({ kind: 'ticket_done', at: '2026-11-02T10:00:00Z', ticket: 'MOCK-9' })).toBe('From MOCK-9, marked Done')
    expect(versionSourceWords(null)).toBe('Not known until the first check')
  })
})

describe('the list', () => {
  it('keeps every row in Software we watch, so the count is the real number', () => {
    expect(rowsMatching(ROWS, '').map((row) => row.status)).toEqual(ROWS.map((row) => row.status))
    expect(rowsMatching(ROWS, '')).toHaveLength(ROWS.length)
  })

  it('filters by name or repository, whatever the case', () => {
    expect(rowsMatching(ROWS, 'LANG')).toHaveLength(1)
    expect(rowsMatching(ROWS, 'hashicorp')).toHaveLength(1)
    expect(rowsMatching(ROWS, 'zzz')).toHaveLength(0)
  })

  it('makes one decision for the whole check, however many rows wait on it', () => {
    const waiting = (id: string, approval: string | null): WatchedSoftwareView => ({ ...ROWS[0]!, id, status: 'awaiting_approval', approval_id: approval })
    expect(decisionsOf(ROWS)).toEqual([{ approvalId: 'apr_01JBB', software: 1 }])
    expect(decisionsOf([waiting('a', 'apr_1'), waiting('b', 'apr_1'), waiting('c', 'apr_1')])).toEqual([{ approvalId: 'apr_1', software: 3 }])
    expect(decisionsOf([waiting('a', null)])).toEqual([])
    expect(decisionsOf([])).toEqual([])
  })

  it('counts what needs action as one decision per check plus each address that needs a person, as the page’s Needs attention does', () => {
    const moved: WatchedSoftwareView = { ...ROWS[0]!, id: 'm', status: 'behind', approval_id: null, moved_to: 'new/name' }
    const gone: WatchedSoftwareView = { ...ROWS[0]!, id: 'g', status: 'cant_check', approval_id: null, not_found: true }
    expect(watchAttention(ROWS)).toBe(1)
    expect(watchAttention([...ROWS, moved, gone])).toBe(3)
    expect(watchAttention([])).toBe(0)
  })
})

describe('the count line under the title', () => {
  const rowsOf = (...states: readonly (readonly [SoftwareStatus, string | null])[]) =>
    states.map(([status, ours], index): WatchedSoftwareView => ({ ...ROWS[0]!, id: `r${String(index)}`, status, our_version: ours }))

  it('counts what has a newer version, what can’t be checked and what isn’t checked yet, from every row', () => {
    expect(countLine(ROWS)).toBe('3 have a newer version · 1 can’t be checked · 1 not checked yet')
  })

  it('counts a row whose upgrade ticket waits for a yes, or is open, as having a newer version', () => {
    expect(countLine(rowsOf(['awaiting_approval', '1.0.0'], ['ticket_open', '1.0.0']))).toBe('2 have a newer version')
    expect(countLine(rowsOf(['behind', '1.0.0'], ['up_to_date', '1.0.0']))).toBe('1 has a newer version')
  })

  it('leaves out a part with nothing in it', () => {
    expect(countLine(rowsOf(['cant_check', '1.0.0'], ['cant_check', '1.0.0'], ['up_to_date', '1.0.0']))).toBe('2 can’t be checked')
    expect(countLine(rowsOf(['not_checked', null]))).toBe('1 not checked yet')
  })

  it('says everything is up to date only when every row has a version to be up to date with', () => {
    expect(countLine(rowsOf(['up_to_date', '1.0.0'], ['up_to_date', '2.0.0']))).toBe('Everything is up to date.')
    expect(countLine(rowsOf(['up_to_date', '1.0.0'], ['up_to_date', null]))).toBe('Nothing newer yet.')
  })

  it('has no count for an empty list', () => {
    expect(countLine([])).toBeNull()
  })

  it('never claims a row is up to date while the list has one not checked yet', () => {
    expect(countLine(rowsOf(['up_to_date', '1.0.0'], ['not_checked', null]))).not.toMatch(/up to date|Nothing newer/i)
  })
})

describe('what checks a row', () => {
  const REGISTRY = capabilitiesFixture.capabilities as CapabilityView[]
  const withReleases = (state: CapabilityView['state']) => REGISTRY.map((c) => (c.id === 'github.releases' ? { ...c, state } : c))

  it('says it is checked on GitHub while the registry says GitHub releases can be read', () => {
    expect(checkedOnWords('github', REGISTRY)).toBe('Checked on GitHub')
  })

  it('never says it is checked while the registry says GitHub is not working, or before the registry is there', () => {
    expect(checkedOnWords('github', withReleases('down'))).toBe('On GitHub')
    expect(checkedOnWords('github', withReleases('needs_setup'))).toBe('On GitHub')
    expect(checkedOnWords('github', undefined)).toBe('On GitHub')
    expect(checkedOnWords('github', REGISTRY.filter((c) => c.id !== 'github.releases'))).toBe('On GitHub')
  })

  it('names the tickets the yes covers, in the singular too', () => {
    expect(decisionTitle(3)).toBe('The latest check wants to raise 3 upgrade tickets.')
    expect(decisionTitle(1)).toBe('The latest check wants to raise 1 upgrade ticket.')
  })

  it('says who the bar waits for, and why when the person is the reason', () => {
    expect(waitingWords('own_work')).toBe('Waiting for another Approver. This check is your own work.')
    expect(waitingWords('not_an_approver')).toBe('Waiting for an Approver.')
    expect(waitingWords(null)).toBe('Waiting for an Approver.')
  })

  it('says the count of matches in words', () => {
    expect([0, 1, 3].map(matches)).toEqual(['No matches', '1 match', '3 matches'])
  })
})

describe('the newest version', () => {
  const failed = ROWS.find((r) => r.status === 'cant_check') as WatchedSoftwareView

  it('keeps the version an earlier check read, and says when, after a check that could not read the source', () => {
    expect(newestOf(failed)).toEqual({ version: '0.115.2', note: 'Last read Mon 9 Nov, 9:00' })
  })

  it('says it is not known when no check has read it, and not checked yet before the first check', () => {
    expect(newestOf({ ...failed, newest_version: null, newest_read_at: null })).toEqual({ version: 'Not known', note: null })
    const fresh = ROWS.find((r) => r.status === 'not_checked') as WatchedSoftwareView
    expect(newestOf(fresh)).toEqual({ version: 'Not checked yet', note: null })
  })

  it('shows the version alone when the latest check read it', () => {
    const read = ROWS.find((r) => r.status === 'behind') as WatchedSoftwareView
    expect(newestOf(read)).toEqual({ version: '1.2.16', note: null })
  })
})

describe('a row that can’t be checked', () => {
  it('says its own reason, then when it is checked again', () => {
    const reason = 'GitHub answered 404 Not Found.'
    expect(cantCheckWords(reason, { scheduled: true, paused: false })).toBe('GitHub answered 404 Not Found. It will try again at the next check.')
    expect(cantCheckWords(reason, { scheduled: false, paused: false })).toBe('GitHub answered 404 Not Found. It is checked again when an Operator presses Check now.')
    expect(cantCheckWords(reason, { scheduled: true, paused: true })).toBe('GitHub answered 404 Not Found. It is checked again once the watchlist is resumed.')
  })

  it('says it can’t check right now when the platform gave no reason', () => {
    expect(cantCheckWords(null, { scheduled: true, paused: false })).toBe('Can’t check right now. It will try again at the next check.')
  })
})

describe('words that depend on the schedule and on pausing', () => {
  it('offers Check now with no schedule, but not while the watchlist is paused', () => {
    expect(noScheduleWords({ operator: true, paused: false })).toBe('No schedule. Press Check now to check by hand.')
    expect(noScheduleWords({ operator: false, paused: false })).toBe('No schedule. An Operator can press Check now to check by hand.')
    for (const operator of [true, false]) {
      expect(noScheduleWords({ operator, paused: true })).toBe('No schedule. Paused. No check runs until an Operator resumes it.')
    }
  })

  it('says how new software gets checked on an empty list', () => {
    expect(emptyWords({ operator: true, scheduled: true, paused: false })).toBe('Add the tools your team runs. Each one is checked at the next check.')
    expect(emptyWords({ operator: true, scheduled: false, paused: false })).toBe('Add the tools your team runs, then press Check now to check them.')
    expect(emptyWords({ operator: true, scheduled: false, paused: true })).toBe('Add the tools your team runs. They can be checked once an Operator resumes the watchlist.')
    expect(emptyWords({ operator: false, scheduled: true, paused: false })).toBe('An Operator can add the tools your team runs.')
  })
})

describe('the schedule', () => {
  it('shows the next check in Singapore time and names the owner', () => {
    expect(singaporeTime('2026-11-23T09:00:00+08:00')).toBe('Mon 23 Nov, 9:00')
    expect(singaporeTime('2026-11-23T01:00:00Z')).toBe('Mon 23 Nov, 9:00')
    expect(singaporeTime('2026-11-01T16:30:00Z'), 'the midnight hour keeps its 0').toBe('Mon 2 Nov, 0:30')
    expect(singaporeTime('not a time')).toBe('')
    expect(scheduleWords(SCHEDULE)).toBe('Checked every Monday at 9:00, set by Alice.')
    expect(scheduleOwnerWords(SCHEDULE)).toBe('Scheduled checks count as Alice’s work, so Alice can’t approve them.')
  })

  it('for a London schedule, names London after its time and gives the next check in London, as the watchlist’s row on the Workflows list does', () => {
    const london: ScheduleView = { ...SCHEDULE, time_zone: 'Europe/London', next_at: '2026-11-23T09:00:00Z' }
    expect(scheduleWords(london)).toBe('Checked every Monday at 9:00 London time, set by Alice.')
    expect(nextCheckWords(london, false)).toBe('Next check Mon 23 Nov, 9:00, London time.')
    const row = { state: 'on' as const, next_run_at: london.next_at, schedule: { day: london.day, at: london.at, time_zone: london.time_zone, owner_name: london.owner_name } }
    expect(nextRunWords(row, new Date('2026-11-04T15:00:00+08:00'))).toBe('Mon 23 Nov, 9:00 London time')
  })

  it('for a zone the browser cannot read, names it from its id and gives the next check in Singapore time, saying so', () => {
    const build = formatterFactory.build
    const spy = vi.spyOn(formatterFactory, 'build').mockImplementation((zone) => {
      if (zone === 'Europe/Kyiv') throw new RangeError(`Invalid time zone specified: ${zone}`)
      return build(zone)
    })
    try {
      for (const [time_zone, name] of [['Europe/Kyiv', 'Kyiv'], ['Factory', 'Factory']] as const) {
        const schedule: ScheduleView = { ...SCHEDULE, time_zone, next_at: '2026-11-23T09:00:00Z' }
        expect(scheduleWords(schedule)).toBe(`Checked every Monday at 9:00 ${name} time, set by Alice.`)
        expect(nextCheckWords(schedule, false)).toBe('Next check Mon 23 Nov, 17:00, Singapore time.')
      }
    } finally {
      spy.mockRestore()
    }
  })

  it('says why a held schedule is not running, and paused wins over held', () => {
    const removed: ScheduleView = { ...SCHEDULE, next_at: null, held: 'owner_removed' }
    const notOperator: ScheduleView = { ...removed, held: 'owner_not_an_operator' }
    expect(nextCheckWords(SCHEDULE, false)).toBe('Next check Mon 23 Nov, 9:00, Singapore time.')
    expect(nextCheckWords(removed, false)).toBe('Not running: Alice is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(nextCheckWords(notOperator, false)).toBe('Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.')
    expect(nextCheckWords({ ...removed, owner_name: '' }, false)).toBe('Not running: its owner is no longer on the People list. An Operator can take it over by saving the schedule.')
    const paused: ScheduleView = { ...SCHEDULE, next_at: null }
    for (const schedule of [paused, removed, notOperator]) expect(nextCheckWords(schedule, true)).toBe('Paused. No check runs until an Operator resumes it.')
    expect([scheduleRuns(SCHEDULE), scheduleRuns(removed), scheduleRuns(notOperator), scheduleRuns(null)]).toEqual([true, false, false, false])
  })

  it('offers every day the platform takes, so a watchlist set to every weekday shows it', () => {
    expect(DAYS).toEqual(Object.keys(dayOption))
    expect(DAYS.map((day) => dayOption[day]).slice(0, 3)).toEqual(['Every day', 'Every weekday', 'Monday'])
  })
})

describe('a row’s history', () => {
  it('gives the declined record on the line of the check that found the newer version, in the row note’s words', () => {
    const langgraph = ROWS.find((r) => r.status === 'behind')!
    const record = 'Declined by Bob. Nothing was written. Reason: Wrong version. The tickets will be proposed again at the next check, Mon 16 Nov, 9:00.'
    const words = historyOf(langgraph, nameOf, record).map((line) => line.words)
    expect(words).toContain(`Found 1.2.16. ${record}`)
    expect(words.join(' ')).not.toMatch(/created|Checked\. The newest version/)
    expect(historyOf(langgraph, nameOf, null).map((line) => line.words)).toContain('Checked. The newest version is 1.2.16.')
  })

  it('says who used the new address and who put it back, from and to, newest first', () => {
    const row: WatchedSoftwareView = {
      ...(ROWS.find((r) => r.name === 'FastAPI') as WatchedSoftwareView),
      address_changes: [
        { kind: 'undo', from_repo: 'fastapi/fastapi', to_repo: 'tiangolo/fastapi', by: 'alice', at: '2026-11-10T03:00:00Z' },
        { kind: 'use', from_repo: 'tiangolo/fastapi', to_repo: 'fastapi/fastapi', by: 'alice', at: '2026-11-10T02:00:00Z' },
      ],
    }
    const words = historyOf(row, nameOf, null).map((line) => line.words)
    expect(words).toContain('Alice put the address back to tiangolo/fastapi. It was fastapi/fastapi.')
    expect(words).toContain('Alice used the new address fastapi/fastapi. It was tiangolo/fastapi.')
    expect(words.indexOf('Alice put the address back to tiangolo/fastapi. It was fastapi/fastapi.')).toBeLessThan(words.indexOf('Alice used the new address fastapi/fastapi. It was tiangolo/fastapi.'))
  })

  it('says our version came from the ticket once it is marked Done', () => {
    const row: WatchedSoftwareView = {
      ...(ROWS.find((r) => r.name === 'LangGraph') as WatchedSoftwareView),
      our_version: '1.2.16',
      our_version_source: { kind: 'ticket_done', at: '2026-11-17T03:00:00Z', ticket: 'MOCK-143' },
    }
    const words = historyOf(row, nameOf, null).map((line) => line.words)
    expect(words).toContain('Our version moved to 1.2.16. It came from MOCK-143, marked Done.')
    expect(words.at(-1)).toBe('Added by Alice.')
  })

  it('lists what happened newest first, after what is true now', () => {
    const row: WatchedSoftwareView = {
      ...(ROWS.find((r) => r.name === 'LangGraph') as WatchedSoftwareView),
      status: 'ticket_open',
      open_ticket: 'MOCK-150',
      checked_at: '2026-11-10T01:00:00Z',
      newest_read_at: '2026-11-10T01:00:00Z',
      our_version: '1.2.16',
      our_version_source: { kind: 'ticket_done', at: '2026-11-17T03:00:00Z', ticket: 'MOCK-143' },
    }
    expect(historyOf(row, nameOf, null).map((line) => line.when)).toEqual(['Now', 'Tue 17 Nov, 11:00', 'Tue 10 Nov, 9:00', 'Mon 2 Nov, 18:00'])
    const given = ROWS.find((r) => r.name === 'FastAPI') as WatchedSoftwareView
    expect(historyOf(given, nameOf, null).map((line) => line.words).slice(-2)).toEqual(['Our version is 0.115.0. Given when added.', 'Added by Alice.'])
  })

  it('says why a check failed and when it will try again', () => {
    const row = ROWS.find((r) => r.status === 'cant_check') as WatchedSoftwareView
    expect(historyOf(row, nameOf, null).map((line) => line.words)).toContain('Couldn’t check. GitHub answered 404 Not Found.')
  })

  it('keeps the newest version an earlier check read below the check that failed', () => {
    const row = ROWS.find((r) => r.status === 'cant_check') as WatchedSoftwareView
    expect(historyOf(row, nameOf, null)).toEqual([
      { when: 'Mon 16 Nov, 9:00', words: 'Couldn’t check. GitHub answered 404 Not Found.' },
      { when: 'Mon 9 Nov, 9:00', words: 'Checked. The newest version is 0.115.2.' },
      { when: 'Mon 2 Nov, 18:00', words: 'Our version is 0.115.0. Given when added.' },
      { when: 'Mon 2 Nov, 18:00', words: 'Added by Alice.' },
    ])
  })

  it('says a new row was not checked yet', () => {
    const row = ROWS.find((r) => r.status === 'not_checked') as WatchedSoftwareView
    expect(historyOf(row, nameOf, null)[0]).toEqual({ when: 'Not yet', words: 'Not checked yet.' })
  })
})

describe('what the team runs', () => {
  const base = ROWS[0] as WatchedSoftwareView

  it('shows the version somebody gave, with where it came from', () => {
    const given = { ...base, our_version: '1.2.14', our_version_source: { kind: 'given', at: '2026-11-02T10:00:00Z', ticket: null }, compared_from: null } as WatchedSoftwareView
    expect(oursOf(given)).toEqual({ version: '1.2.14', note: 'Given when added' })
  })

  it('says Not known, with the version the checks compare from, never as the version the team runs', () => {
    const first = { ...base, our_version: null, our_version_source: { kind: 'first_check', at: '2026-11-09T01:00:00Z', ticket: null }, compared_from: '8.2.0' } as WatchedSoftwareView
    expect(oursOf(first)).toEqual({ version: 'Not known', note: 'Telling you about releases newer than 8.2.0, the newest the first check read' })
  })

  it('says Not known before any check has read the newest release', () => {
    const fresh = { ...base, our_version: null, our_version_source: null, compared_from: null } as WatchedSoftwareView
    expect(oursOf(fresh)).toEqual({ version: 'Not known', note: 'The first check reads the newest release. Later checks tell you about newer ones' })
  })

  it('tells the row history what the checks compare from', () => {
    const first = { ...base, our_version: null, our_version_source: { kind: 'first_check', at: '2026-11-09T01:00:00Z', ticket: null }, compared_from: '8.2.0' } as WatchedSoftwareView
    const words = historyOf(first, nameOf, null).map((line) => line.words)
    expect(words).toContain('Our version is not known. Later checks tell about releases newer than 8.2.0, the newest the first check read.')
    expect(words.some((line) => line.startsWith('Our version is 8.2.0'))).toBe(false)
  })
})

describe('the status of a row whose version is not known', () => {
  it('does not claim Up to date when nothing is known to be up to date with', () => {
    expect(statusWords({ status: 'up_to_date', our_version: null })).toBe('Nothing newer yet')
    expect(statusWords({ status: 'up_to_date', our_version: '1.2.16' })).toBe('Up to date')
    expect(statusWords({ status: 'behind', our_version: null })).toBe('New version')
  })
})

describe('when the watchlist checks next, for what a declined check says happens next', () => {
  const schedule: ScheduleView = { ...SCHEDULE, next_at: '2026-11-23T01:00:00Z', held: null }

  it('is the schedule’s next check, in its zone', () => {
    expect(nextCheckOf({ state: 'on', schedule })).toEqual({ at: '2026-11-23T01:00:00Z', zone: schedule.time_zone })
  })

  it('is nothing while the watchlist is paused, held or unscheduled', () => {
    expect(nextCheckOf({ state: 'paused', schedule })).toBeNull()
    expect(nextCheckOf({ state: 'on', schedule: { ...schedule, held: 'owner_removed' } })).toBeNull()
    expect(nextCheckOf({ state: 'on', schedule: null })).toBeNull()
    expect(nextCheckOf(null)).toBeNull()
  })
})
