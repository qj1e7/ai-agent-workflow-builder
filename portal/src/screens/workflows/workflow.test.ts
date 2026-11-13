import { describe, expect, it, vi } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import heldWatchlist from '../../../../contracts/fixtures/builder/use-case.held.json'
import pausedWatchlist from '../../../../contracts/fixtures/builder/use-case.paused.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import working from '../../../../contracts/fixtures/views/failure.working.json'
import declined from '../../../../contracts/fixtures/views/rejected.final.json'
import scheduled from '../../../../contracts/fixtures/views/scheduled.pending.json'
import waiting from '../../../../contracts/fixtures/views/success.awaiting_approval.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import threeWaiting from '../../../../contracts/fixtures/views/watchlist.awaiting_approval.json'
import heldSchedule from '../../../../contracts/fixtures/watchlist/schedule.held.json'
import { ApiError } from '../../api/client'
import { errorWords } from '../../api/errors'
import { createLatch } from '../../api/latch'
import type { RunView, ScheduleHold, ScheduleView, UseCaseView, VersionSchedule, VersionView } from '../../api/types'
import { placeAfterRedraw } from '../../ui/focus'
import { nextCheckWords, TAKE_OVER_WORDS } from '../software/software'
import {
  agentsOf,
  bannerOf,
  changeProblem,
  controlsOf,
  deleteWords,
  formatterFactory,
  changeWords,
  heldNote,
  lifeWords,
  lastRunWords,
  nextRunOf,
  lineWhen,
  meansOutOfDate,
  menuActionsOf,
  nextRunAt,
  nextRunWords,
  placeOf,
  PLACES_IN_PAGE_ORDER,
  pillOf,
  pressChange,
  pressRunNow,
  rereadWhenOutOfDate,
  mayChangeSchedule,
  rowAction,
  scheduleSaver,
  scheduleSavedWords,
  rowsOf,
  rowLine,
  sentenceOf,
  stageOfRun,
  runWhen,
  runsOf,
  stepTag,
  timesZone,
  whenWords,
  workflowPath,
  versionWords,
  undoneWords,
  undoProblem,
  leftOutWords,
  type ChangeOutcome,
  type LastRun,
  type RunNowOutcome,
  type Viewer,
} from './workflow'
import { stageWords } from '../run/words'

const WATCHLIST = watchlistUseCase as UseCaseView
const PAUSED = pausedWatchlist as UseCaseView
const AGENTS = agentUseCase as UseCaseView
const HELD = heldWatchlist as UseCaseView
const run = (view: unknown, change: Partial<RunView> = {}) => ({ ...(view as RunView), ...change }) as RunView
const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob', carol: 'Carol' }
const nameOf = (id: string) => NAMES[id] ?? id
const words = (error: unknown) => errorWords(error, 'dev')

const ALICE: Viewer = { id: 'alice', operator: true, approver: true }
const BOB: Viewer = { id: 'bob', operator: false, approver: true }
const CAROL: Viewer = { id: 'carol', operator: true, approver: false }

const NOW = new Date('2026-11-04T15:00:00+08:00')

const LAST: LastRun = { run_id: 'run_07', state: 'rejected', at: '2026-10-26T01:41:00Z', test: false, declined_by: 'bob', decline_reason: null, approved_by: [], proposed: 3, written: 0, tickets: true, you_can_decide: false, retryable: false, reason: null }
const lastOf = (change: Partial<LastRun>): Pick<UseCaseView, 'last_run'> => ({ last_run: { ...LAST, ...change } })

describe('the status words', () => {
  it('say whether a workflow is on or paused', () => {
    expect(lifeWords('on')).toBe('On')
    expect(lifeWords('paused')).toBe('Paused')
  })

  it('read a run as the same stage words the row and the banner use', () => {
    expect(stageOfRun(run(waiting))).toMatchObject({ state: 'awaiting_approval', count: 1, tickets: true })
    expect(stageWords(stageOfRun(run(threeWaiting)), nameOf)).toBe('Waiting for a yes')
    expect(stageWords(stageOfRun(run(failed)), nameOf)).toBe('An agent could not finish its work')
  })

  it('say what a finished run wrote and who said yes, and that nothing was new', () => {
    expect(stageWords(stageOfRun(run(done)), nameOf)).toBe('1 ticket created, approved by Bob')
    expect(stageWords(stageOfRun(run(done, { outcome: 'nothing_to_write', written: [] })), nameOf)).toBe('Nothing new to write')
  })

  it('say a declined run wrote nothing, with who declined', () => {
    expect(stageWords(stageOfRun(run(declined)), nameOf)).toBe('Declined by Bob. Nothing was written.')
  })

  it('say a run skipped while an earlier one waits for a yes, and need nobody', () => {
    const skipped = run(failed, { state: 'skipped', waiting_run_id: 'run_06' })
    expect(stageWords(stageOfRun(skipped), nameOf)).toBe('Skipped. An earlier run is still waiting for a yes.')
    expect(rowLine({ schedule: null, ...lastOf({ state: 'skipped' }) }, NOW, nameOf)).toBe('No schedule · last run Mon 26 Oct, skipped. An earlier run is still waiting for a yes.')
  })

  it('say a run that is still going is running', () => {
    for (const view of [working, scheduled]) expect(stageWords(stageOfRun(run(view)), nameOf)).toBe('Running')
  })
})

describe('when a workflow runs next', () => {
  const at = '2026-11-16T01:00:00Z'
  const schedule = { ...(WATCHLIST.schedule as NonNullable<UseCaseView['schedule']>), held: null }
  it('is its next run while its schedule will start one, in the schedule’s zone', () => {
    expect(nextRunOf({ state: 'on', next_run_at: at, schedule })).toEqual({ at, zone: schedule.time_zone })
  })

  it('is nothing while it is paused, held or has no next run', () => {
    expect(nextRunOf({ state: 'paused', next_run_at: at, schedule })).toBeNull()
    expect(nextRunOf({ state: 'on', next_run_at: at, schedule: { ...schedule, held: 'owner_removed' } })).toBeNull()
    expect(nextRunOf({ state: 'on', next_run_at: null, schedule: null })).toBeNull()
    expect(nextRunOf(undefined)).toBeNull()
  })
})

describe('a workflow row’s line', () => {
  const line = (change: Partial<LastRun>, schedule: UseCaseView['schedule'] = { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null }) =>
    rowLine({ schedule, ...lastOf(change) }, NOW, nameOf)

  it('says no runs yet for a workflow that never ran', () => {
    expect(rowLine({ schedule: null, last_run: null }, NOW, nameOf)).toBe('No schedule · no runs yet')
    expect(rowLine({ schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null }, last_run: null }, NOW, nameOf)).toBe('Mon 9:00 · no runs yet')
  })

  it('gives its schedule, then the day of the last run and where it stands', () => {
    expect(line({ state: 'failed', declined_by: null, reason: 'AgentError', at: '2026-11-04T00:00:00Z' })).toBe('Daily 8:00 · last run today, an agent could not finish its work')
    expect(line({ state: 'awaiting_approval', declined_by: null })).toBe('Daily 8:00 · last run Mon 26 Oct, waiting for a yes')
  })

  it('names who declined, and never says a ticket was created', () => {
    expect(line({ decline_reason: 'Wrong version' })).toBe('Daily 8:00 · last run Mon 26 Oct, declined by Bob. Nothing was written.')
    expect(line({ declined_by: null })).toBe('Daily 8:00 · last run Mon 26 Oct, declined. Nothing was written.')
  })

  it('counts what a finished run wrote, as tickets or changes, and says when nothing was new', () => {
    expect(line({ state: 'succeeded', declined_by: null, proposed: 3, written: 3, approved_by: ['bob'] })).toBe('Daily 8:00 · last run Mon 26 Oct, 3 tickets created, approved by Bob')
    expect(line({ state: 'succeeded', declined_by: null, proposed: 2, written: 2, tickets: false })).toBe('Daily 8:00 · last run Mon 26 Oct, 2 changes written')
    expect(line({ state: 'succeeded', declined_by: null, proposed: 0, tickets: false })).toBe('Daily 8:00 · last run Mon 26 Oct, nothing new to write')
  })

  it('says what a run that is writing creates, and that one in progress is running', () => {
    expect(line({ state: 'acting', declined_by: null, proposed: 1 })).toBe('Daily 8:00 · last run Mon 26 Oct, creating the ticket')
    for (const state of ['pending', 'working', 'proposed'] as const) expect(line({ state, declined_by: null })).toBe('Daily 8:00 · last run Mon 26 Oct, running')
  })

  it('gives the side panel the whole declined record, with the reason and any first yes', () => {
    const words = (change: Partial<LastRun>) => lastRunWords(lastOf(change), NOW, nameOf)
    expect(words({})).toBe('Mon 26 Oct: Declined by Bob. Nothing was written.')
    expect(words({ decline_reason: 'Wrong version' })).toBe('Mon 26 Oct: Declined by Bob. Nothing was written. Reason: Wrong version.')
    expect(words({ declined_by: 'alice', approved_by: ['bob'] })).toBe('Mon 26 Oct: Approved by Bob, then declined by Alice. Nothing was written.')
    expect(words({ state: 'failed', declined_by: null, reason: null })).toBe('Mon 26 Oct: Stopped')
    expect(words({ state: 'failed', declined_by: null, at: '2026-11-04T00:00:00Z', reason: 'AgentError' })).toBe('Today 8:00: An agent could not finish its work')
  })

  it('gives a workflow’s own pill only to a run that needs a yes or has stopped, and a running one reads On', () => {
    expect(pillOf({ state: 'awaiting_approval' })).toEqual({ tone: 'wait', pill: 'Waiting for a yes' })
    expect(pillOf({ state: 'failed' })).toEqual({ tone: 'bad', pill: 'Stopped' })
    expect(pillOf({ state: 'working' })).toEqual({ tone: 'new', pill: null })
    expect(pillOf({ state: 'rejected' }).pill).toBeNull()
    expect(pillOf({ state: 'succeeded' }).pill).toBeNull()
  })
})

describe('times, in Singapore time', () => {
  it('give a run’s start as today or its date, with the time', () => {
    expect(runWhen('2026-11-04T02:14:00Z', NOW)).toBe('Today, 10:14')
    expect(runWhen('2026-11-03T02:14:00Z', NOW)).toBe('Tue 3 Nov, 10:14')
    expect(runWhen('2027-01-04T01:00:00Z', NOW)).toBe('Mon 4 Jan 2027, 9:00')
  })

  it('give the list’s line a shorter date, with the time only for today', () => {
    expect(lineWhen('2026-11-04T02:14:00Z', NOW)).toBe('Today 10:14')
    expect(lineWhen('2026-11-03T02:14:00Z', NOW)).toBe('Tue 3 Nov')
  })

  it('count the day in Singapore, not in UTC', () => {
    expect(runWhen('2026-11-03T17:30:00Z', NOW)).toBe('Today, 1:30')
  })
})

describe('the next run', () => {
  it('reads Paused while the workflow is paused, the date when it has a schedule, and Not scheduled otherwise', () => {
    expect(nextRunWords(PAUSED, NOW)).toBe('Paused')
    expect(nextRunWords(WATCHLIST, NOW)).toBe('Mon 9 Nov, 9:00')
    expect(nextRunWords(AGENTS, NOW)).toBe('Not scheduled')
  })
})

const heldBy = (held: ScheduleHold, owner_name = 'Carol'): UseCaseView => ({ ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name, held } })

describe('a schedule held because its owner can no longer run it', () => {
  it('says why on the workflow page, and the next run reads Not running', () => {
    expect(heldNote(heldBy('owner_removed'))).toBe('Not running: Carol is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(heldNote(heldBy('owner_not_an_operator'))).toBe('Not running: Carol can no longer run workflows. An Operator can take it over by saving the schedule.')
    expect(heldNote(heldBy('owner_removed', ' '))).toBe('Not running: its owner is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect([nextRunWords(heldBy('owner_removed'), NOW), nextRunWords(HELD, NOW)]).toEqual(['Not running', 'Not running'])
  })

  it('says why in the Software page’s words, since an Operator takes either schedule over by saving it', () => {
    expect(heldNote(HELD)).toBe(nextCheckWords(heldSchedule.schedule as ScheduleView, false))
    expect(heldNote(heldBy('owner_removed'))).toContain(TAKE_OVER_WORDS)
  })

  it('gives way to Paused, and says nothing while the schedule runs', () => {
    const paused: UseCaseView = { ...heldBy('owner_not_an_operator'), state: 'paused' }
    expect([heldNote(paused), nextRunWords(paused, NOW)]).toEqual([null, 'Paused'])
    expect([heldNote(WATCHLIST), heldNote(PAUSED), heldNote(AGENTS)]).toEqual([null, null, null])
  })
})

describe('when it runs', () => {
  it('gives the schedule’s own day and time, in Singapore time', () => {
    expect(whenWords(WATCHLIST)).toEqual({ words: 'Every Monday at 9:00', small: 'Singapore time (SGT).' })
    expect(whenWords({ schedule: { day: 'every_day', at: '17:30', time_zone: 'Asia/Singapore', owner_name: 'Alice' } })).toEqual({ words: 'Every day at 17:30', small: 'Singapore time (SGT).' })
    expect(whenWords({ schedule: { day: 'weekdays', at: '15:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } })).toEqual({ words: 'Every weekday at 15:00', small: 'Singapore time (SGT).' })
  })

  it('names the schedule’s own time zone when it is not Singapore', () => {
    const at = (time_zone: string) => whenWords({ schedule: { day: 'every_day', at: '17:30', time_zone, owner_name: 'Alice' } }).small
    expect(at('Europe/London')).toBe('London time.')
    expect(at('America/Los_Angeles')).toBe('Los Angeles time.')
    expect(at('UTC')).toBe('UTC.')
    expect(at('Etc/GMT+8'), 'Etc/GMT+8 is eight hours behind UTC').toBe('GMT-8.')
    expect(at('Etc/GMT-8')).toBe('GMT+8.')
    expect(at('Etc/GMT-14')).toBe('GMT+14.')
    expect([at('Etc/GMT+0'), at('Etc/GMT-0')], 'no offset is UTC').toEqual(['UTC.', 'UTC.'])
    expect(at('Etc/UTC')).toBe('UTC.')
    expect(at('Pacific/Port_Moresby')).toBe('Port Moresby time.')
    expect(at('Not/AZone'), 'a name the browser cannot read is named from its id').toBe('AZone time.')
    expect(at('Factory'), 'Factory is a real id the browser rejects').toBe('Factory time.')
    for (const utc of ['GMT', 'Etc/GMT', 'Etc/UCT', 'UCT', 'Universal', 'Zulu', 'Greenwich']) expect(at(utc), utc).toBe('UTC.')
    for (const utc of ['Etc/GMT0', 'GMT0', 'GMT+0', 'GMT-0']) expect(at(utc), utc).toBe('UTC.')
    expect(at('America/Port-au-Prince')).toBe('Port au Prince time.')
    expect(at('Africa/Porto-Novo')).toBe('Porto Novo time.')
    expect(at('America/Blanc-Sablon')).toBe('Blanc Sablon time.')
    expect(at('Asia/Ust-Nera')).toBe('Ust Nera time.')
    expect(at('America/Argentina/Buenos_Aires')).toBe('Buenos Aires time.')
    expect(at('EST5EDT'), 'a zone with no city shows its id, because today’s offset can be wrong on the run’s date').toBe('EST5EDT time.')
    expect(at('')).toBe('Singapore time (SGT).')
  })

  it('builds a formatter once per zone name, readable or not', () => {
    const build = vi.spyOn(formatterFactory, 'build')
    const now = new Date('2026-11-04T07:00:00Z')
    for (let i = 0; i < 5; i++) for (const zone of ['Pacific/Fiji', 'Not/AnotherZone', 'Asia/Singapore']) runWhen('2026-11-04T09:00:00Z', now, zone)
    const zones = build.mock.calls.map(([zone]) => zone)
    build.mockRestore()
    expect(zones.toSorted().filter((zone) => zone !== 'Asia/Singapore')).toEqual(['Not/AnotherZone', 'Pacific/Fiji'])
    expect(new Set(zones).size, 'no name is built twice').toBe(zones.length)
  })

  it('shows the next run in the schedule’s own time zone, and names the zone when it is not Singapore', () => {
    const london = { day: 'every_day' as const, at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' }
    const next = { name: 'Watchlist', state: 'on' as const, next_run_at: '2026-11-04T09:00:00Z', schedule: london }
    expect(nextRunWords(next, NOW)).toBe('Today, 9:00 London time')
    expect(nextRunAt(next.next_run_at, NOW, 'Europe/London')).toBe('Today, 9:00 London time')
    expect(nextRunWords({ ...next, schedule: { ...london, time_zone: 'Asia/Singapore' } }, NOW)).toBe('Today, 17:00')
    expect(nextRunAt(next.next_run_at, NOW, 'UTC')).toBe('Today, 9:00 UTC')
    expect(changeWords('resume', next, NOW)).toBe('Resumed. Next run Today, 9:00 London time.')
    expect(scheduleSavedWords(next, NOW)).toBe('Saved. Next run Today, 9:00 London time.')
  })

  it('says nothing more next to a Singapore time, or one with no zone, as every other time in the Portal is Singapore’s', () => {
    expect(nextRunAt('2026-11-04T09:00:00Z', NOW, 'Asia/Singapore')).toBe('Today, 17:00')
    expect(nextRunAt('2026-11-04T09:00:00Z', NOW)).toBe('Today, 17:00')
    expect(nextRunAt('2026-11-04T09:00:00Z', NOW, '')).toBe('Today, 17:00')
    expect([timesZone('Asia/Singapore'), timesZone(undefined), timesZone('Europe/London')]).toEqual(['Singapore time', 'Singapore time', 'London time'])
  })

  it('names a zone the browser cannot read from its id, and gives its times in Singapore with Singapore time next to them', () => {
    const build = formatterFactory.build
    const spy = vi.spyOn(formatterFactory, 'build').mockImplementation((zone) => {
      if (zone === 'Europe/Kyiv') throw new RangeError(`Invalid time zone specified: ${zone}`)
      return build(zone)
    })
    const kyiv = { day: 'every_day' as const, at: '09:00', time_zone: 'Europe/Kyiv', owner_name: 'Alice' }
    const next = { state: 'on' as const, next_run_at: '2026-11-04T09:00:00Z', schedule: kyiv }
    const factory = { ...next, schedule: { ...kyiv, time_zone: 'Factory' } }
    try {
      expect(whenWords(next).small).toBe('Kyiv time.')
      expect(nextRunWords(next, NOW), 'Kyiv would be 11:00, so the time is Singapore’s and says so').toBe('Today, 17:00 Singapore time')
      expect(timesZone('Europe/Kyiv')).toBe('Singapore time')
      expect(whenWords(factory).small).toBe('Factory time.')
      expect(nextRunWords(factory, NOW)).toBe('Today, 17:00 Singapore time')
      expect(scheduleSavedWords(factory, NOW)).toBe('Saved. Next run Today, 17:00 Singapore time.')
    } finally {
      spy.mockRestore()
    }
  })

  it('keeps the schedule while the workflow is paused, because Paused shows in the next run', () => {
    expect(whenWords(PAUSED)).toEqual({ words: 'Every Monday at 9:00', small: 'Singapore time (SGT).' })
    expect(nextRunWords(PAUSED, NOW)).toBe('Paused')
  })

  it('says only Run now starts a workflow with no schedule, on or paused', () => {
    expect(whenWords(AGENTS)).toEqual({ words: 'No schedule', small: 'An Operator starts it with Run now.' })
    const paused: UseCaseView = { ...AGENTS, state: 'paused' }
    expect(whenWords(paused)).toEqual({ words: 'No schedule', small: 'An Operator starts it with Run now.' })
  })
})

describe('the steps of what it does', () => {
  it('say which steps only read, which ask for a yes and which change data after one', () => {
    expect(WATCHLIST.plan.map((block) => stepTag(block.kind))).toEqual([
      { words: 'Reads only', writes: false },
      { words: 'Asks an Approver in Teams', writes: false },
      { words: 'Changes data, waits for a yes', writes: true },
    ])
  })
})

describe('the runs of a workflow', () => {
  const runs = [run(scheduled), run(done), run(declined), run(failed)]

  it('keep only that workflow’s runs, newest first', () => {
    expect(runsOf(runs, 'uc_01JB7').map((r) => r.run_id)).toEqual(['run_01JBA', 'run_01JB9', 'run_01JB8'])
  })
})

describe('the agents on a workflow', () => {
  it('start with the Planner, then each agent card, each linking to its card', () => {
    expect(agentsOf(AGENTS)).toEqual([
      { face: 'planner', name: 'Planner', to: '/settings?tab=how&show=agents&agent=planner' },
      { face: 'version_checker', name: 'Version checker', to: '/settings?tab=how&show=agents&agent=crd_version_checker' },
    ])
  })

  it('name the Version checker for the Software watchlist, which keeps no cards of its own', () => {
    expect(agentsOf(WATCHLIST).map((agent) => agent.name)).toEqual(['Planner', 'Version checker'])
  })
})

describe('the button at the end of a row', () => {
  const last = (change: Partial<LastRun>): LastRun => ({ ...LAST, declined_by: null, ...change })
  const yes = (youCanDecide: boolean) => last({ state: 'awaiting_approval', you_can_decide: youCanDecide })
  const stopped = last({ state: 'failed', retryable: true, reason: 'AgentError' })

  it('offers to decide exactly when the platform says the person can decide', () => {
    expect(rowAction(yes(true), BOB)).toEqual({ kind: 'decide', runId: 'run_07' })
    expect(rowAction(yes(false), BOB)).toBeNull()
  })

  it('offers nothing on a run the person may not decide, whoever they are', () => {
    expect(rowAction(yes(false), ALICE)).toBeNull()
    expect(rowAction(yes(true), CAROL)).toEqual({ kind: 'decide', runId: 'run_07' })
  })

  it('shows Operators why a run stopped, and Approvers nothing', () => {
    expect(rowAction(stopped, CAROL)).toEqual({ kind: 'why', runId: 'run_07' })
    expect(rowAction(stopped, BOB)).toBeNull()
  })

  it('is empty when the last run needs nobody', () => {
    expect(rowAction(last({ state: 'succeeded' }), ALICE)).toBeNull()
    expect(rowAction(last({}), ALICE)).toBeNull()
    expect(rowAction(null, ALICE)).toBeNull()
  })
})

describe('where a row opens', () => {
  it('opens the Software page for the Software watchlist, as the prototype does', () => {
    expect(workflowPath(WATCHLIST)).toBe('/software')
    expect(workflowPath(PAUSED)).toBe('/software')
  })

  it('opens the workflow page for any other workflow', () => {
    expect(workflowPath(AGENTS)).toBe('/workflows/uc_01JD0')
  })
})

describe('the manage controls of a workflow page', () => {
  it('give an Operator Run now, Pause and Delete while it is on, and Resume and Delete while it is paused', () => {
    for (const operator of [ALICE, CAROL]) {
      expect(controlsOf(AGENTS, operator)).toEqual(['run', 'pause', 'delete'])
      expect(controlsOf({ ...AGENTS, state: 'paused' }, operator)).toEqual(['resume', 'delete'])
    }
  })

  it('give an Approver who is not an Operator none', () => {
    expect(controlsOf(AGENTS, BOB)).toEqual([])
    expect(controlsOf({ ...AGENTS, state: 'paused' }, BOB)).toEqual([])
  })

  it('keep Pause and Resume in one place, and Run now and Delete in the menu, so a press that finds the workflow changed hands focus to a control still on the page', () => {
    const shown = (useCase: UseCaseView) => controlsOf(useCase, ALICE).map(placeOf)
    expect(shown({ ...AGENTS, state: 'paused' })).toEqual(['switch', 'more'])
    expect(placeAfterRedraw(PLACES_IN_PAGE_ORDER, placeOf('run'), shown({ ...AGENTS, state: 'paused' }))).toBe('more')
    expect(placeAfterRedraw(PLACES_IN_PAGE_ORDER, placeOf('pause'), shown({ ...AGENTS, state: 'paused' }))).toBe('switch')
  })

  it('give nobody any for the Software watchlist, which is looked after on the Software page', () => {
    for (const viewer of [ALICE, BOB, CAROL]) {
      expect(controlsOf(WATCHLIST, viewer)).toEqual([])
      expect(controlsOf(PAUSED, viewer)).toEqual([])
    }
  })
})

describe('the rows of the list', () => {
  const last = (change: Partial<LastRun>): LastRun => ({ ...LAST, declined_by: null, ...change })
  const nudge: UseCaseView = { ...AGENTS, use_case_id: 'uc_nudge', name: 'Stale ticket nudge', instruction: 'Ask owners about old tickets.', state: 'paused', last_run: null }
  const bugs: UseCaseView = { ...AGENTS, use_case_id: 'uc_bugs', name: 'Morning bug report check', instruction: 'Raise a ticket for each new bug report.', last_run: last({ run_id: 'run_bugs', state: 'failed', retryable: true, reason: 'AgentError' }) }
  const watchlist = (viewer: Viewer): UseCaseView => ({ ...WATCHLIST, last_run: last({ run_id: 'run_01JB8', state: 'awaiting_approval', you_can_decide: viewer === BOB }) })
  const useCasesFor = (viewer: Viewer) => [nudge, watchlist(viewer), bugs]
  const ids = (rows: { useCase: UseCaseView }[]) => rows.map((row) => row.useCase.use_case_id)

  it('put the rows that need you first and keep the platform’s order for the rest', () => {
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'all', ''))).toEqual(['uc_01JB7', 'uc_nudge', 'uc_bugs'])
    expect(ids(rowsOf(useCasesFor(CAROL), CAROL, 'all', ''))).toEqual(['uc_bugs', 'uc_nudge', 'uc_01JB7'])
  })

  it('take each row’s action from its last run, and none when Needs you already offers that run', () => {
    expect(rowsOf(useCasesFor(ALICE), ALICE, 'all', '').map((row) => row.action?.runId ?? null)).toEqual(['run_bugs', null, null])
    expect(rowsOf(useCasesFor(CAROL), CAROL, 'all', '', new Set(['run_bugs'])).map((row) => row.action)).toEqual([null, null, null])
  })

  it('filter to what stopped and what is paused', () => {
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'stopped', ''))).toEqual(['uc_bugs'])
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'paused', ''))).toEqual(['uc_nudge'])
  })

  it('find a workflow by words in its name or what it does, in any case', () => {
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'all', '  BUG '))).toEqual(['uc_bugs'])
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'all', 'old tickets'))).toEqual(['uc_nudge'])
    expect(ids(rowsOf(useCasesFor(BOB), BOB, 'paused', 'bug'))).toEqual([])
  })
})

describe('Run now', () => {
  function harness() {
    const started: { useCaseId: string; idempotencyKey: string }[] = []
    const outcomes: RunNowOutcome[] = []
    const opened: string[] = []
    const refused: unknown[] = []
    const latch = createLatch()
    let key = 'key-1'
    const press = () =>
      pressRunNow(
        latch,
        (input, outcome) => {
          started.push(input)
          outcomes.push(outcome)
        },
        { useCaseId: 'uc_01JB7', idempotencyKey: key },
        { open: (runId) => opened.push(runId), refused: (error) => refused.push(error) },
      )
    return { started, outcomes, opened, refused, press, rekey: (next: string) => (key = next) }
  }

  it('starts one run for two presses in one tick', () => {
    const h = harness()
    h.press()
    h.press()
    expect(h.started).toEqual([{ useCaseId: 'uc_01JB7', idempotencyKey: 'key-1' }])
  })

  it('opens the new run’s page when the platform answers', () => {
    const h = harness()
    h.press()
    h.outcomes[0]?.onSuccess?.({ run_id: 'run_new' })
    h.outcomes[0]?.onSettled?.()
    expect(h.opened).toEqual(['run_new'])
  })

  it('hands a refusal to the page, so it can read the workflow again', () => {
    const h = harness()
    const paused = new ApiError(409, { detail: 'This workflow is paused. Resume it to start a run.' })
    h.press()
    h.outcomes[0]?.onError?.(paused)
    expect(h.refused).toEqual([paused])
    expect(h.opened).toEqual([])
  })

  it('lets the next press through once the platform answered, with the key it is given', () => {
    const h = harness()
    h.press()
    h.outcomes[0]?.onSettled?.()
    h.press()
    expect(h.started.map((s) => s.idempotencyKey)).toEqual(['key-1', 'key-1'])
    expect(h.opened).toEqual([])
  })
})

describe('pausing, resuming, deleting and putting back', () => {
  it('sends one change for two presses in one tick, and the next once the platform answered', () => {
    const sent: string[] = []
    const outcomes: ChangeOutcome<unknown>[] = []
    const settled: string[] = []
    const latch = createLatch()
    const press = (change: 'pause' | 'resume' | 'delete' | 'restore') =>
      pressChange(
        latch,
        (outcome) => {
          sent.push(change)
          outcomes.push(outcome)
        },
        { onSettled: () => settled.push(change) },
      )
    press('pause')
    press('delete')
    expect(sent).toEqual(['pause'])
    outcomes[0]?.onSettled?.()
    expect(settled).toEqual(['pause'])
    press('resume')
    expect(sent).toEqual(['pause', 'resume'])
  })

  it('say what happened in plain words', () => {
    expect(changeWords('pause', PAUSED, NOW)).toBe('Paused. Software watchlist won’t run until you resume it.')
    expect(changeWords('resume', WATCHLIST, NOW)).toBe('Resumed. Next run Mon 9 Nov, 9:00.')
    expect(changeWords('resume', AGENTS, NOW)).toBe('Resumed. LangGraph release check can run again.')
    expect(changeWords('delete', AGENTS, NOW)).toBe('Deleted LangGraph release check.')
    expect(changeWords('restore', AGENTS, NOW)).toBe('Put back.')
  })

  it('say why a change did not go through', () => {
    const name = 'LangGraph release check'
    expect(changeProblem('pause', name, new ApiError(404, { detail: 'No such workflow' }), words)).toBe('Could not pause LangGraph release check. It was deleted.')
    expect(changeProblem('restore', name, new ApiError(410, { detail: 'gone' }), words)).toBe('Could not put LangGraph release check back. It was deleted more than a day ago.')
    expect(changeProblem('restore', name, new ApiError(404, { detail: 'No such workflow' }), words)).toBe('Could not put LangGraph release check back. The platform has no record of it.')
    expect(changeProblem('delete', name, new ApiError(403, { detail: 'Only an Operator can change workflows.' }), words)).toBe('Could not delete LangGraph release check. Only an Operator can change workflows.')
    expect(changeProblem('resume', name, new ApiError(503, null), words)).toBe('Could not resume LangGraph release check. The platform had a problem. Try again in a moment.')
  })
})

describe('a refusal that means the page shows an old state', () => {
  it('is a 409, such as Run now on a workflow someone else paused', () => {
    expect(meansOutOfDate(new ApiError(409, { detail: 'This workflow is paused. Resume it to start a run.' }))).toBe(true)
  })

  it('is a 404, such as any press on a workflow someone else deleted', () => {
    expect(meansOutOfDate(new ApiError(404, { detail: 'No such workflow' }))).toBe(true)
  })

  it('is not any other answer', () => {
    for (const status of [403, 410, 503]) expect(meansOutOfDate(new ApiError(status, null)), String(status)).toBe(false)
    expect(meansOutOfDate(new TypeError('Failed to fetch'))).toBe(false)
  })
})

describe('rereading a workflow that changed under the Operator', () => {
  const run = (error: unknown) => {
    const said: string[] = []
    rereadWhenOutOfDate('uc_1', (pressed: string) => said.push(`focus ${pressed}`), (id) => said.push(`reread ${id}`))('switch')(error)
    return said
  }

  it('moves focus and rereads on a 409 or a 404', () => {
    expect(run(new ApiError(409, null))).toEqual(['focus switch', 'reread uc_1'])
    expect(run(new ApiError(404, null))).toEqual(['focus switch', 'reread uc_1'])
  })

  it('does nothing for any other answer', () => {
    expect(run(new ApiError(503, null))).toEqual([])
    expect(run(new Error('offline'))).toEqual([])
  })
})

describe('changing a workflow’s schedule', () => {
  it('is for Operators, and not for the Software watchlist, whose schedule is saved on the Software page', () => {
    expect([ALICE, BOB, CAROL].map((viewer) => mayChangeSchedule(AGENTS, viewer))).toEqual([true, false, true])
    expect([ALICE, CAROL].map((viewer) => mayChangeSchedule(WATCHLIST, viewer))).toEqual([false, false])
  })

  it('says when it runs next, in the schedule’s own time', () => {
    const saved = { ...AGENTS, state: 'on' as const, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday' as const, at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } }
    expect(scheduleSavedWords(saved, NOW)).toBe('Saved. Next run Mon 9 Nov, 9:00.')
  })

  it('says a paused workflow runs on it once resumed, since a paused one names no next run', () => {
    expect(scheduleSavedWords({ ...AGENTS, state: 'paused', next_run_at: null }, NOW)).toBe('Saved. It runs on this schedule once you resume it.')
  })

  it('reads the workflow again, off the pressed control, when the platform says it changed or is gone', () => {
    const seen: string[] = []
    const again = rereadWhenOutOfDate('uc_1', () => seen.push('focus'), (id) => seen.push(`reread ${id}`))('schedule')
    again(new ApiError(409, { detail: 'The Software watchlist’s schedule is saved on the Software page.' }))
    again(new ApiError(403, { detail: 'Only an Operator can change workflows.' }))
    expect(seen).toEqual(['focus', 'reread uc_1'])
  })
})

describe('what happens when a schedule is saved', () => {
  const saved = { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z' } as UseCaseView
  type Answers = { onSuccess: (view: UseCaseView) => void; onError: (failure: unknown) => void }
  const setup = (answer: (answers: Answers) => void) => {
    const seen: string[] = []
    const form = { onSuccess: () => seen.push('closed'), onError: (failure: unknown) => seen.push(`shown ${(failure as ApiError).status}`) }
    const mutate = (_body: unknown, answers: Answers) => answer(answers)
    const save = scheduleSaver(mutate, {
      useCaseId: 'uc_1',
      now: NOW,
      say: (text) => seen.push(`said ${text}`),
      refocus: () => seen.push('focus'),
      reread: (id) => seen.push(`reread ${id}`),
    })
    save({ day: 'monday', at: '09:00' }, form)
    return seen
  }

  it('closes the form and says the schedule is saved, with the next run', () => {
    expect(setup((answers) => answers.onSuccess(saved))).toEqual(['closed', 'said Saved. Next run Mon 9 Nov, 9:00.'])
  })

  it('shows the refusal and reads the workflow again when it changed or is gone', () => {
    expect(setup((answers) => answers.onError(new ApiError(409, { detail: 'x' })))).toEqual(['shown 409', 'focus', 'reread uc_1'])
    expect(setup((answers) => answers.onError(new ApiError(404, { detail: 'x' })))).toEqual(['shown 404', 'focus', 'reread uc_1'])
  })

  it('only shows any other refusal', () => {
    expect(setup((answers) => answers.onError(new ApiError(403, { detail: 'x' })))).toEqual(['shown 403'])
  })
})

describe('the More actions menu', () => {
  it('holds Run now, Change schedule and Delete in that order, with Delete last', () => {
    expect(menuActionsOf(AGENTS, ALICE)).toEqual(['run', 'schedule', 'delete'])
  })

  it('drops Run now while paused, because a paused workflow starts nothing', () => {
    expect(menuActionsOf({ ...AGENTS, state: 'paused' }, ALICE)).toEqual(['schedule', 'delete'])
  })

  it('is empty for an Approver who is not an Operator, and for the Software watchlist', () => {
    expect(menuActionsOf(AGENTS, BOB)).toEqual([])
    expect(menuActionsOf(WATCHLIST, ALICE)).toEqual([])
  })
})

describe('the status banner', () => {
  const NOW = new Date('2026-11-04T15:00:00+08:00')
  const on = { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } } as UseCaseView
  const last = (change: Partial<LastRun>): LastRun => ({ ...LAST, declined_by: null, ...change })
  const facts = (change: object) => ({ useCase: on, viewer: ALICE, now: NOW, ...change })
  const withLast = (change: Partial<LastRun>) => ({ ...on, last_run: last(change) }) as UseCaseView
  const stoppedAt = (change: Partial<LastRun> = {}) => withLast({ run_id: 'run_stop', state: 'failed', at: '2026-11-04T00:00:00Z', reason: 'AgentError', ...change })

  it('says a workflow that is on has its next run, and offers no button', () => {
    expect(bannerOf(facts({}))).toEqual({ tone: 'ok', text: 'On. Next run Mon 9 Nov, 9:00.', action: null })
  })

  it('says a workflow with no schedule runs when an Operator presses Run now', () => {
    expect(bannerOf(facts({ useCase: AGENTS })).text).toBe('On. It has no schedule, so it runs when an Operator presses Run now.')
  })

  it('holds Resume for an Operator while paused, and tells an Approver an Operator resumes it, with no action', () => {
    const paused = { ...on, state: 'paused' } as UseCaseView
    expect(bannerOf(facts({ useCase: paused }))).toEqual({ tone: 'off', text: 'Paused. It won’t run until you resume it.', action: { kind: 'resume' } })
    expect(bannerOf(facts({ useCase: paused, viewer: BOB }))).toEqual({ tone: 'off', text: 'Paused. It won’t run until an Operator resumes it.', action: null })
  })

  it('lets a paused workflow say Paused even when its last run stopped', () => {
    expect(bannerOf(facts({ useCase: { ...stoppedAt(), state: 'paused' } })).tone).toBe('off')
  })

  it('for a stopped run, says when it stopped and why, as one sentence', () => {
    expect(bannerOf(facts({ useCase: stoppedAt() }))).toEqual({ tone: 'bad', text: 'Stopped today at 8:00. An agent could not finish its work.', action: { kind: 'stopped', runId: 'run_stop', retryable: false } })
  })

  it('names the stop from the run’s reason, as the Workflows list does', () => {
    const useCase = stoppedAt({ reason: 'TimedOut' })
    expect(bannerOf(facts({ useCase })).text).toMatch(/^Stopped .+\. A step took too long\.$/)
    expect(bannerOf(facts({ useCase, viewer: BOB })).text).toBe(bannerOf(facts({ useCase })).text)
  })

  it('carries whether the platform says a stopped run can be retried', () => {
    expect(bannerOf(facts({ useCase: stoppedAt({ retryable: true }) })).action).toEqual({ kind: 'stopped', runId: 'run_stop', retryable: true })
  })

  it('gives an Approver the stop without an action', () => {
    expect(bannerOf(facts({ useCase: stoppedAt(), viewer: BOB })).action).toBeNull()
  })

  it('for a run waiting for a yes, offers Review and decide only when the platform says the person may decide', () => {
    const mayDecide = withLast({ state: 'awaiting_approval', you_can_decide: true })
    const mayNot = withLast({ state: 'awaiting_approval', you_can_decide: false })
    expect(bannerOf(facts({ useCase: mayDecide })).action).toEqual({ kind: 'decide', runId: 'run_07' })
    expect(bannerOf(facts({ useCase: mayNot })).action, 'someone who may not decide can still open the run, as in the sketch').toEqual({ kind: 'open', runId: 'run_07' })
    expect(bannerOf(facts({ useCase: mayNot })).tone).toBe('wait')
    expect(bannerOf(facts({ useCase: mayNot })).text).toBe('3 tickets are waiting for a yes.')
  })

  it('says a held schedule is not running, and why', () => {
    const held = { ...on, next_run_at: null, schedule: { ...on.schedule, held: 'owner_removed' } } as UseCaseView
    expect(bannerOf(facts({ useCase: held })).text).toContain('Not running')
  })
})

describe('what Delete says is lost', () => {
  it('names the workflow, its schedule, the runs that stay and the Undo', () => {
    expect(deleteWords('LangGraph release check', 3)).toBe(
      'LangGraph release check leaves Workflows, and its schedule stops, so no more runs start. Its 3 past runs stay in the record, with who approved what. Undo stays in the message that follows.',
    )
  })

  it('says so when it has no runs', () => {
    expect(deleteWords('Nudge', 0)).toContain('It has no runs yet.')
  })

  it('says one past run stays, in the singular', () => {
    expect(deleteWords('Nudge', 1)).toContain('Its 1 past run stays in the record')
  })

  it('says nothing about runs until they have loaded', () => {
    const words = deleteWords('Nudge', null)
    expect(words).not.toMatch(/runs yet|past run/)
    expect(words).toBe('Nudge leaves Workflows, and its schedule stops, so no more runs start. Undo stays in the message that follows.')
  })
})

describe('the Versions words', () => {
  const nameOf = (id: string) => ({ alice: 'Alice', carol: 'Carol' })[id] ?? id
  const at = (day: VersionSchedule['day'], clock: string, zone = 'Asia/Singapore'): VersionSchedule => ({ day, at: clock, time_zone: zone })
  const version = (change: Partial<VersionView> & Pick<VersionView, 'version'>): VersionView => ({
    at: '2026-11-04T01:10:00Z',
    by: 'carol',
    via: 'page',
    change: null,
    undid: null,
    running: false,
    ...change,
  })
  const moved = (before: VersionSchedule | null, after: VersionSchedule | null) => ({ schedule: { before, after } })

  it('says a first schedule was set, and an Undo of it leaves none', () => {
    expect(versionWords(version({ version: 2, change: moved(null, at('monday', '09:00')) }), nameOf)).toBe('Carol set it to run every Monday at 9:00.')
    expect(versionWords(version({ version: 3, undid: 2, change: moved(at('monday', '09:00'), null) }), nameOf)).toBe('Carol undid version 2, so it has no schedule again.')
  })

  it('names a zone that is not Singapore', () => {
    const words = versionWords(version({ version: 2, change: moved(at('monday', '09:00', 'Europe/London'), at('friday', '17:30')) }), nameOf)
    expect(words).toBe('Carol changed when it runs from every Monday at 9:00 London time to every Friday at 17:30.')
  })

  it('says what an Undo published, and that a paused workflow won’t run until it is resumed, as the prototype’s edit card does', () => {
    const schedule = { day: 'weekdays' as const, at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null }
    const undone = { name: 'Morning new-ticket check', version: 3, state: 'on' as const, schedule }
    expect(undoneWords(undone)).toBe('Undone, as version 3. Morning new-ticket check runs every weekday at 8:00 now.')
    expect(undoneWords({ ...undone, state: 'paused' })).toBe('Undone, as version 3. Morning new-ticket check is paused, so it won’t run until you resume it.')
    expect(undoneWords({ ...undone, schedule: null })).toBe('Undone, as version 3. Morning new-ticket check has no schedule now.')
  })

  it('tells the undo route’s two refusals apart', () => {
    const later = new ApiError(409, { detail: 'The workflow changed again since this version, so Undo would throw that change away.' })
    const notAChange = new ApiError(409, { detail: 'Only a change of when the workflow runs can be undone.' })
    expect(undoProblem(4, 'Nudge', later, words)).toBe('Could not undo version 4. Nudge changed again since, so Undo would throw that change away.')
    expect(undoProblem(1, 'Nudge', notAChange, words)).toBe('Could not undo version 1. Only a change of when Nudge runs can be undone.')
    expect(undoProblem(2, 'Nudge', new ApiError(404, { detail: 'No such workflow' }), words)).toBe('Could not undo version 2. It was deleted.')
  })
})

describe('leftOutWords', () => {
  it('quotes each part in her words, and says nothing when nothing was left out', () => {
    expect(leftOutWords([])).toBeNull()
    expect(leftOutWords(['Friday'])).toBe('Left out: “Friday”. It was set up without that part.')
    expect(leftOutWords(['from GitLab', 'colour them by team'])).toBe('Left out: “from GitLab” and “colour them by team”. It was set up without those parts.')
  })
})

describe('the sentence on the workflow page', () => {
  const every = { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } as const
  const scheduledAt = (schedule: UseCaseView['schedule']) => ({ ...AGENTS, schedule })

  it('says when it runs, what it checks, and that a ticket is made only after a yes', () => {
    expect(sentenceOf(scheduledAt(every))).toBe('Every day at 8:00, check langchain-ai/langgraph on GitHub for a new release. If there is one, create an upgrade ticket in Jira project MOCK, after a yes.')
  })

  it('names a zone that is not Singapore, and a weekday', () => {
    expect(sentenceOf(scheduledAt({ ...every, day: 'monday', time_zone: 'Europe/London' })).startsWith('Every Monday at 8:00 London time, check')).toBe(true)
  })

  it('says it runs when an Operator presses Run now while it has no schedule, and never guesses a time', () => {
    expect(sentenceOf(AGENTS)).toBe('Check langchain-ai/langgraph on GitHub for a new release when an Operator presses Run now. If there is one, create an upgrade ticket in Jira project MOCK, after a yes.')
  })

  it('says it tells you here when the workflow writes nothing', () => {
    const readOnly = { ...scheduledAt(every), plan: AGENTS.plan.filter((block) => block.kind !== 'write_action') }
    expect(sentenceOf(readOnly)).toBe('Every day at 8:00, check langchain-ai/langgraph on GitHub for a new release. If there is one, tell me here.')
  })

  it('falls back to what the Operator wrote when the workflow is not a release check', () => {
    const other = { ...AGENTS, agents: [{ card_id: 'crd_other', card_version: 1, name: 'Other', values: {} }] }
    expect(sentenceOf(other)).toBe(AGENTS.instruction)
    expect(sentenceOf({ ...AGENTS, agents: [{ ...AGENTS.agents[0]!, values: {} }] })).toBe(AGENTS.instruction)
  })
})
