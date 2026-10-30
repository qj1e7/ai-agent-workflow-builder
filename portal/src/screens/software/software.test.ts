import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import type { ScheduleView, WatchedSoftwareView } from '../../api/types'
import {
  addProblems,
  cantCheckWords,
  checkClock,
  checkName,
  checkRepo,
  checkVersion,
  countIn,
  emptyWords,
  groupsOf,
  historyOf,
  matches,
  newestOf,
  nextCheckWords,
  noScheduleWords,
  repoOf,
  scheduleOwnerWords,
  scheduleRuns,
  scheduleWords,
  singaporeTime,
  statusLabel,
  versionSourceWords,
} from './software'

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

  it('lets our version stay empty and wants three numbers otherwise', () => {
    expect(checkVersion('')).toEqual({ ok: true, value: null })
    expect(checkVersion('1.2.14')).toEqual({ ok: true, value: '1.2.14' })
    for (const bad of ['1.2', 'v1.2.3', '1.2.x', '1.2.3-beta']) expect(checkVersion(bad).ok, bad).toBe(false)
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
      behind: 'Behind',
      awaiting_approval: 'Ticket waiting for a yes',
      ticket_open: 'Ticket open',
      up_to_date: 'Up to date',
      not_checked: 'Not checked yet',
    })
  })

  it('says where our version came from', () => {
    expect(versionSourceWords({ kind: 'given', at: '2026-11-02T10:00:00Z', ticket: null })).toBe('Given when added')
    expect(versionSourceWords({ kind: 'first_check', at: '2026-11-02T10:00:00Z', ticket: null })).toBe('Taken from the first check')
    expect(versionSourceWords({ kind: 'ticket_done', at: '2026-11-02T10:00:00Z', ticket: 'MOCK-9' })).toBe('From MOCK-9, marked Done')
    expect(versionSourceWords(null)).toBe('Not known until the first check')
  })
})

describe('the list', () => {
  it('splits rows by whether a person has to look', () => {
    const groups = groupsOf(ROWS, '')
    expect(groups.needs.map((row) => row.status)).toEqual(['cant_check', 'behind', 'awaiting_approval', 'ticket_open'])
    expect(groups.notChecked.map((row) => row.name)).toEqual(['Terraform'])
    expect(groups.upToDate.map((row) => row.name)).toEqual(['n8n'])
    expect(countIn(groups)).toBe(ROWS.length)
  })

  it('filters by name or repository, whatever the case', () => {
    expect(countIn(groupsOf(ROWS, 'LANG'))).toBe(1)
    expect(countIn(groupsOf(ROWS, 'hashicorp'))).toBe(1)
    expect(countIn(groupsOf(ROWS, 'zzz'))).toBe(0)
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
    expect(scheduleWords(SCHEDULE)).toBe('Checked every Monday at 9:00, set by Alice.')
    expect(scheduleOwnerWords(SCHEDULE)).toBe('Scheduled checks count as Alice’s work, so Alice can’t approve them.')
  })

  it('says why a held schedule is not running, and paused wins over held', () => {
    const removed: ScheduleView = { ...SCHEDULE, next_at: null, held: 'owner_removed' }
    const notOperator: ScheduleView = { ...removed, held: 'owner_not_an_operator' }
    expect(nextCheckWords(SCHEDULE, false)).toBe('Next check Mon 23 Nov, 9:00, Singapore time.')
    expect(nextCheckWords(removed, false)).toBe('Not running: Alice is no longer on the list. An Operator can take it over by saving the schedule.')
    expect(nextCheckWords(notOperator, false)).toBe('Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.')
    expect(nextCheckWords({ ...removed, owner_name: '' }, false)).toBe('Not running: its owner is no longer on the list. An Operator can take it over by saving the schedule.')
    for (const schedule of [SCHEDULE, removed, notOperator]) expect(nextCheckWords(schedule, true)).toBe('Paused. No check runs until an Operator resumes it.')
    expect([scheduleRuns(SCHEDULE), scheduleRuns(removed), scheduleRuns(notOperator), scheduleRuns(null)]).toEqual([true, false, false, false])
  })
})

describe('a row’s history', () => {
  it('says our version came from the ticket once it is marked Done', () => {
    const row: WatchedSoftwareView = {
      ...(ROWS.find((r) => r.name === 'LangGraph') as WatchedSoftwareView),
      our_version: '1.2.16',
      our_version_source: { kind: 'ticket_done', at: '2026-11-17T03:00:00Z', ticket: 'MOCK-143' },
    }
    const words = historyOf(row, nameOf).map((line) => line.words)
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
    expect(historyOf(row, nameOf).map((line) => line.when)).toEqual(['Now', 'Tue 17 Nov, 11:00', 'Tue 10 Nov, 9:00', 'Mon 2 Nov, 18:00'])
    const given = ROWS.find((r) => r.name === 'FastAPI') as WatchedSoftwareView
    expect(historyOf(given, nameOf).map((line) => line.words).slice(-2)).toEqual(['Our version is 0.115.0. Given when added.', 'Added by Alice.'])
  })

  it('says why a check failed and when it will try again', () => {
    const row = ROWS.find((r) => r.status === 'cant_check') as WatchedSoftwareView
    expect(historyOf(row, nameOf).map((line) => line.words)).toContain('Couldn’t check. GitHub answered 404 Not Found.')
  })

  it('keeps the newest version an earlier check read below the check that failed', () => {
    const row = ROWS.find((r) => r.status === 'cant_check') as WatchedSoftwareView
    expect(historyOf(row, nameOf)).toEqual([
      { when: 'Mon 16 Nov, 9:00', words: 'Couldn’t check. GitHub answered 404 Not Found.' },
      { when: 'Mon 9 Nov, 9:00', words: 'Checked. The newest version is 0.115.2.' },
      { when: 'Mon 2 Nov, 18:00', words: 'Our version is 0.115.0. Given when added.' },
      { when: 'Mon 2 Nov, 18:00', words: 'Added by Alice.' },
    ])
  })

  it('says a new row was not checked yet', () => {
    const row = ROWS.find((r) => r.status === 'not_checked') as WatchedSoftwareView
    expect(historyOf(row, nameOf)[0]).toEqual({ when: 'Not yet', words: 'Not checked yet.' })
  })
})
