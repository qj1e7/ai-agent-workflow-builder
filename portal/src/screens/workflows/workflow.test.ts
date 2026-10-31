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
import type { RunView, ScheduleHold, ScheduleView, UseCaseView } from '../../api/types'
import { placeAfterRedraw } from '../../ui/focus'
import { nextCheckWords, TAKE_OVER_WORDS } from '../software/software'
import {
  agentsOf,
  changeProblem,
  controlsOf,
  faceStates,
  formatterFactory,
  changeWords,
  heldNote,
  latestRuns,
  lifeWords,
  lineWhen,
  meansOutOfDate,
  nextRunWords,
  placeOf,
  PLACES_IN_PAGE_ORDER,
  pressChange,
  pressRunNow,
  rereadWhenOutOfDate,
  mayChangeSchedule,
  rowAction,
  scheduleSaver,
  scheduleSavedWords,
  rowsOf,
  runFact,
  runWhen,
  runsOf,
  stepTag,
  whenWords,
  workflowPath,
  type ChangeOutcome,
  type RunNowOutcome,
  type Viewer,
} from './workflow'

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

describe('the status words', () => {
  it('say whether a workflow is on or paused', () => {
    expect(lifeWords('on')).toBe('On')
    expect(lifeWords('paused')).toBe('Paused')
  })

  it('say a run that waits needs a yes, and how many changes wait', () => {
    expect(runFact(run(waiting), nameOf)).toEqual({ tone: 'wait', pill: 'Needs a yes', words: '1 ticket is waiting for a yes.' })
    expect(runFact(run(threeWaiting), nameOf).words).toBe('3 tickets are waiting for a yes.')
  })

  it('say a run that failed stopped, and why in plain words', () => {
    expect(runFact(run(failed), nameOf)).toEqual({ tone: 'bad', pill: 'Stopped', words: 'Stopped. An agent could not finish its work.' })
  })

  it('say a run that finished is done, with what it wrote and who said yes', () => {
    expect(runFact(run(done), nameOf)).toEqual({ tone: 'ok', pill: null, words: 'Done. 1 ticket created, approved by Bob.' })
    expect(runFact(run(done, { outcome: 'nothing_to_write', written: [] }), nameOf).words).toBe('Done. Nothing to write.')
  })

  it('say a declined run wrote nothing, with no pill, because nobody needs to act', () => {
    expect(runFact(run(declined), nameOf)).toEqual({ tone: 'ok', pill: null, words: 'Declined by Bob. Nothing was written.' })
  })

  it('say a run that is still going is running', () => {
    for (const view of [working, scheduled]) expect(runFact(run(view), nameOf)).toEqual({ tone: 'new', pill: 'Running', words: 'Running now.' })
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
    expect(at('Etc/UTC')).toBe('UTC.')
    expect(at('Pacific/Port_Moresby')).toBe('Port Moresby time.')
    expect(at('Not/AZone'), 'a name the browser cannot read is shown as Singapore, as the times are').toBe('Singapore time (SGT).')
    for (const utc of ['GMT', 'Etc/GMT', 'Etc/UCT', 'UCT', 'Universal', 'Zulu', 'Greenwich']) expect(at(utc), utc).toBe('UTC.')
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

  it('shows the next run in the schedule’s own time zone', () => {
    const london = { day: 'every_day' as const, at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' }
    const next = { name: 'Watchlist', state: 'on' as const, next_run_at: '2026-11-04T09:00:00Z', schedule: london }
    expect(nextRunWords(next, NOW)).toBe('Today, 9:00')
    expect(nextRunWords({ ...next, schedule: { ...london, time_zone: 'Asia/Singapore' } }, NOW)).toBe('Today, 17:00')
    expect(changeWords('resume', next, NOW)).toBe('Resumed. Next run Today, 9:00.')
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

  it('give each workflow its newest run, whatever order the list came in', () => {
    const latest = latestRuns(runs)
    expect(latest.get('uc_01JB7')?.run_id).toBe('run_01JBA')
    expect(latest.get('uc_01JBW')?.run_id).toBe('run_01JBB')
    expect(latest.get('uc_none')).toBeUndefined()
  })
})

describe('the agents on a workflow', () => {
  it('start with the Planner, then each agent card, each linking to its card', () => {
    expect(agentsOf(AGENTS)).toEqual([
      { face: 'planner', name: 'Planner', to: '/agents/planner' },
      { face: 'version_checker', name: 'Version checker', to: '/agents/crd_version_checker' },
    ])
  })

  it('name the Version checker for the Software watchlist, which keeps no cards of its own', () => {
    expect(agentsOf(WATCHLIST).map((agent) => agent.name)).toEqual(['Planner', 'Version checker'])
  })
})

describe('the faces on a workflow', () => {
  it('close their eyes while it is paused, and the last agent waits while a run needs a yes', () => {
    expect(faceStates(PAUSED, run(waiting), 2)).toEqual(['stopped', 'stopped'])
    expect(faceStates(WATCHLIST, run(waiting), 2)).toEqual(['idle', 'waiting'])
  })

  it('stay calm otherwise, so nothing moves without a reason', () => {
    expect(faceStates(WATCHLIST, run(failed), 2)).toEqual(['idle', 'idle'])
    expect(faceStates(WATCHLIST, null, 2)).toEqual(['idle', 'idle'])
  })
})

describe('the button at the end of a row', () => {
  const stopped = run(failed)

  const yes = (youCanDecide: boolean) => run(waiting, { you_can_decide: youCanDecide })

  it('offers to decide exactly when the platform says the person can decide', () => {
    expect(rowAction(yes(true), BOB)).toEqual({ kind: 'decide', runId: 'run_01JB8' })
    expect(rowAction(yes(false), BOB)).toBeNull()
  })

  it('offers nothing on a run the person retried, though they did not start it or own the workflow', () => {
    // Bob is an Approver, did not start the run and does not own the workflow, but he retried it.
    const retried = run(waiting, { started_by: 'carol', you_can_decide: false })
    expect(rowAction(retried, BOB)).toBeNull()
  })

  it('offers nothing on a workflow the person owns, and follows the platform when it says yes', () => {
    const owned = run(waiting, { started_by: 'carol', you_can_decide: false })
    expect(rowAction(owned, ALICE)).toBeNull()
    expect(rowAction(yes(true), CAROL)).toEqual({ kind: 'decide', runId: 'run_01JB8' })
  })

  it('shows Operators why a run stopped, and Approvers nothing', () => {
    expect(rowAction(stopped, CAROL)).toEqual({ kind: 'why', runId: 'run_01JB9' })
    expect(rowAction(stopped, BOB)).toBeNull()
  })

  it('is empty when the latest run needs nobody', () => {
    expect(rowAction(run(done), ALICE)).toBeNull()
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

  it('keep Pause and Resume in one place, so a refused Run now on a workflow someone paused hands focus to Resume', () => {
    const shown = (useCase: UseCaseView) => controlsOf(useCase, ALICE).map(placeOf)
    expect(shown({ ...AGENTS, state: 'paused' })).toEqual(['switch', 'delete'])
    expect(placeAfterRedraw(PLACES_IN_PAGE_ORDER, placeOf('run'), shown({ ...AGENTS, state: 'paused' }))).toBe('switch')
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
  const nudge: UseCaseView = { ...AGENTS, use_case_id: 'uc_nudge', name: 'Stale ticket nudge', instruction: 'Ask owners about old tickets.', state: 'paused' }
  const bugs: UseCaseView = { ...AGENTS, use_case_id: 'uc_bugs', name: 'Morning bug report check', instruction: 'Raise a ticket for each new bug report.' }
  const useCases = [nudge, WATCHLIST, bugs]
  const runsFor = (viewer: Viewer) => [run(failed, { use_case_id: 'uc_bugs', run_id: 'run_bugs' }), run(waiting, { you_can_decide: viewer === BOB })]
  const runs = runsFor(ALICE)
  const ids = (rows: { useCase: UseCaseView }[]) => rows.map((row) => row.useCase.use_case_id)

  it('put the rows that need you first and keep the platform’s order for the rest', () => {
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'all', ''))).toEqual(['uc_01JB7', 'uc_nudge', 'uc_bugs'])
    expect(ids(rowsOf(useCases, runsFor(CAROL), CAROL, 'all', ''))).toEqual(['uc_bugs', 'uc_nudge', 'uc_01JB7'])
  })

  it('carry each workflow’s latest run, or none', () => {
    const rows = rowsOf(useCases, runs, ALICE, 'all', '')
    expect(rows.map((row) => row.latest?.run_id ?? null)).toEqual(['run_bugs', null, 'run_01JB8'])
  })

  it('filter to what needs you, what stopped and what is paused', () => {
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'needs', ''))).toEqual(['uc_01JB7'])
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'stopped', ''))).toEqual(['uc_bugs'])
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'paused', ''))).toEqual(['uc_nudge'])
  })

  it('find a workflow by words in its name or what it does, in any case', () => {
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'all', '  BUG '))).toEqual(['uc_bugs'])
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'all', 'old tickets'))).toEqual(['uc_nudge'])
    expect(ids(rowsOf(useCases, runsFor(BOB), BOB, 'paused', 'bug'))).toEqual([])
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
