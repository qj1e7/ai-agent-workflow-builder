import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import dayOne from '../../../../contracts/fixtures/builder/home.day-one.json'
import type { ApprovalItem, HomeOut, StoppedItem, WaitingItem } from '../../api/types'
import { ApiError } from '../../api/client'
import { actionsOf, comingUpOf, draftWords, leadLine, moreWords, NEEDS_SHOWN, needsOf, retryProblem, waitingWords, wordsOf, type Need } from './home'

const BOB = bobHome as HomeOut
const ALICE = aliceHome as HomeOut
const DAY_ONE = dayOne as HomeOut
const NOW = new Date('2026-11-03T15:00:00+08:00')

const [ASK] = BOB.approvals as [ApprovalItem]
const [STOP] = ALICE.stopped as [StoppedItem]
const [WAIT] = ALICE.waiting_on_others as [WaitingItem]

function ask(runId: string, startedAt: string): ApprovalItem {
  return { ...ASK, run_id: runId, approval_id: `apr_${runId}`, started_at: startedAt }
}

function stop(runId: string, stoppedAt: string): StoppedItem {
  return { ...STOP, run_id: runId, stopped_at: stoppedAt }
}

const keys = (needs: readonly Need[]) => needs.map((need) => need.key)

describe('the order of what needs you', () => {
  it('puts approvals first, then confirmations, then stopped runs', () => {
    const home: HomeOut = { ...BOB, stopped: [STOP], stopped_total: 1 }
    expect(needsOf(home).shown.map((need) => need.kind)).toEqual(['approval', 'confirmation', 'confirmation', 'stopped'])
  })

  it('shows the newest first within each kind, whatever order they came in', () => {
    const home: HomeOut = {
      ...DAY_ONE,
      approvals: [ask('run_old', '2026-11-01T01:00:00Z'), ask('run_new', '2026-11-03T01:00:00Z'), ask('run_mid', '2026-11-02T01:00:00Z')],
      approvals_total: 3,
      stopped: [stop('run_s1', '2026-11-01T01:00:00Z'), stop('run_s2', '2026-11-02T01:00:00Z')],
      stopped_total: 2,
    }
    expect(keys(needsOf(home).shown)).toEqual(['approval:apr_run_new', 'approval:apr_run_mid', 'approval:apr_run_old', 'stopped:run_s2', 'stopped:run_s1'])
  })

  it('keeps the same order for the same moment, so a refresh never swaps two rows', () => {
    const same = '2026-11-03T01:00:00Z'
    const once = needsOf({ ...DAY_ONE, approvals: [ask('run_b', same), ask('run_a', same)], approvals_total: 2 })
    const again = needsOf({ ...DAY_ONE, approvals: [ask('run_a', same), ask('run_b', same)], approvals_total: 2 })
    expect(keys(once.shown)).toEqual(keys(again.shown))
  })

  it(`shows at most ${NEEDS_SHOWN} and counts the rest from the platform's totals`, () => {
    const approvals = Array.from({ length: 10 }, (_, n) => ask(`run_${String(n).padStart(2, '0')}`, `2026-11-03T01:${String(n).padStart(2, '0')}:00Z`))
    const home: HomeOut = { ...BOB, approvals, approvals_total: 50, stopped: [STOP], stopped_total: 1 }
    const needs = needsOf(home)
    expect(needs.shown).toHaveLength(NEEDS_SHOWN)
    expect(needs.shown[0]?.key).toBe('approval:apr_run_09')
    expect(needs.total).toBe(53)
    expect(needs.more).toEqual({ approvals: 40, others: 3 })
  })

  it('says nothing more when everything fits', () => {
    expect(needsOf(BOB).more).toEqual({ approvals: 0, others: 0 })
  })
})

describe('the line under the greeting', () => {
  it('counts what needs you', () => {
    expect(leadLine(1, 4)).toBe('1 thing needs you. Everything else is running.')
    expect(leadLine(3, 4)).toBe('3 things need you. Everything else is running.')
  })

  it('says nothing needs you yet on a team with no workflows, and right now on one with workflows', () => {
    expect(leadLine(0, 0)).toBe('Nothing needs you yet. When a workflow wants to change something, it shows up here and in Teams.')
    expect(leadLine(0, 2)).toBe('Nothing needs you right now. Your workflows are running.')
  })
})

describe('how many more are waiting', () => {
  it('names approvals when only approvals are left out', () => {
    expect(moreWords({ approvals: 40, others: 0 })).toBe('40 more runs are waiting for your yes. The next ones show here as you decide these.')
    expect(moreWords({ approvals: 1, others: 0 })).toBe('1 more run is waiting for your yes. The next ones show here as you decide these.')
  })

  it('counts everything when other items are left out too', () => {
    expect(moreWords({ approvals: 2, others: 1 })).toBe('3 more things need you. The next ones show here as you finish these.')
  })

  it('says nothing when nothing is left out', () => {
    expect(moreWords({ approvals: 0, others: 0 })).toBeNull()
  })
})

describe('each item in words', () => {
  const [approval, address, approver] = needsOf(BOB).shown as [Need, Need, Need]
  const [stopped] = needsOf(ALICE).shown as [Need]

  it('says how many tickets wait for your yes, which workflow, who started it and when, and lists them', () => {
    expect(wordsOf(approval, NOW)).toEqual({
      tone: 'wait',
      title: '1 ticket is waiting for your yes',
      meta: 'Software watchlist · Started by Alice, Today, 10:14',
      lines: ['Upgrade LangGraph from 1.2.14 to 1.2.16'],
      note: null,
      why: null,
    })
  })

  it('names the step of two, and says how many more changes there are than it lists', () => {
    const two = { ...approval, item: { ...ASK, step: 1, steps: 2, changes: 5, first_changes: [{ connector: 'jira', operation: 'update_page', title: null }] } } as Need
    const words = wordsOf(two, NOW)
    expect(words.title).toBe('5 changes are waiting for your yes')
    expect(words.meta).toBe('Software watchlist · Started by Alice, Today, 10:14 · Step 2 of 2')
    expect(words.lines).toEqual(['A change in Jira', 'and 4 more'])
  })

  it('calls the changes tickets only when every one of them is known to be a ticket', () => {
    const ticket = { connector: 'jira', operation: 'create_ticket', title: 'Upgrade LangGraph' }
    const three = [ticket, ticket, ticket]
    expect(wordsOf({ ...approval, item: { ...ASK, changes: 3, first_changes: three } } as Need, NOW).title).toBe('3 tickets are waiting for your yes')
    expect(wordsOf({ ...approval, item: { ...ASK, changes: 5, first_changes: three } } as Need, NOW).title).toBe('5 changes are waiting for your yes')
  })

  it('names a schedule that started a run', () => {
    const scheduled = { ...approval, item: { ...ASK, trigger: 'schedule' } } as Need
    expect(wordsOf(scheduled, NOW).meta).toBe("Software watchlist · Started by Alice's schedule, Today, 10:14")
  })

  it('says a schedule or someone no longer on the list started a run when the platform names no one', () => {
    const gone = { ...approval, item: { ...ASK, started_by_name: null } } as Need
    expect(wordsOf(gone, NOW).meta).toBe('Software watchlist · Started by someone no longer on the list, Today, 10:14')
    const scheduled = { ...approval, item: { ...ASK, started_by_name: null, trigger: 'schedule' } } as Need
    expect(wordsOf(scheduled, NOW).meta).toBe('Software watchlist · Started by a schedule, Today, 10:14')
  })

  it('asks to confirm a new Approver, and a new AI model address', () => {
    expect(wordsOf(approver, NOW)).toMatchObject({ tone: 'tool', title: 'Confirm Dave as an Approver', meta: 'Asked by Alice, Mon 9 Nov, 11:41' })
    expect(wordsOf(address, NOW)).toMatchObject({ tone: 'tool', title: 'Confirm a new AI model address', meta: 'Use ncs-llm-small at ai-gateway.ncs.example · Asked by Alice' })
    expect(wordsOf(address, NOW).note).toContain('Until you confirm it, runs keep using the current model.')
  })

  it('says a run stopped, when, and the AI troubleshooter’s reason and what to do', () => {
    expect(wordsOf(stopped, new Date('2026-11-04T15:00:00+08:00'))).toEqual({
      tone: 'bad',
      title: 'Software watchlist stopped',
      meta: 'Today, 10:14',
      lines: [],
      note: null,
      why: 'An agent could not finish its work. Retry the run. If it fails again, check whether that service is up.',
    })
  })

  it('never uses the retired names in the troubleshooter’s words', () => {
    const unbound = { ...stopped, item: { ...STOP, advice: { ...STOP.advice, explanation: 'The agents proposed an action this use case cannot carry out.' } } } as Need
    expect(wordsOf(unbound, NOW).why).toMatch(/^The agents proposed an action this workflow cannot carry out\./)
  })
})

describe('what each item lets you do', () => {
  const [approval, address, approver] = needsOf(BOB).shown as [Need, Need, Need]
  const [stopped] = needsOf(ALICE).shown as [Need]

  it('opens the run at the decision, and never decides on Home', () => {
    expect(actionsOf(approval)).toEqual([{ kind: 'open', label: 'Review and decide', to: '/runs/run_01JB8' }])
  })

  it('sends a confirmation to its Settings tab', () => {
    expect(actionsOf(approver)).toEqual([{ kind: 'open', label: 'Review in Settings', to: '/settings?tab=people' }])
    expect(actionsOf(address)).toEqual([{ kind: 'open', label: 'Review in Settings', to: '/settings' }])
  })

  it('retries a stopped run the platform can retry, and otherwise opens it', () => {
    expect(actionsOf(stopped)).toEqual([
      { kind: 'retry', label: 'Retry the run', runId: 'run_01JB9' },
      { kind: 'open', label: 'See the run', to: '/runs/run_01JB9' },
    ])
    const final = { ...stopped, item: { ...STOP, retryable: false } } as Need
    expect(actionsOf(final)).toEqual([{ kind: 'open', label: 'See why it stopped', to: '/runs/run_01JB9' }])
  })
})

describe('a retry the platform refused', () => {
  const words = () => 'Check your connection, or try again in a moment.'

  it('says the run may have been retried already when it is no longer stopped', () => {
    expect(retryProblem(new ApiError(409, null), words)).toBe('It can’t be retried now. Someone may have retried it already, so look at the run.')
  })

  it('says it could not retry, in the app’s words for anything else', () => {
    expect(retryProblem(new TypeError('Failed to fetch'), words)).toBe('Could not retry the run. Check your connection, or try again in a moment.')
  })
})

describe('what you wait on, your drafts and what runs next', () => {
  it('says whose yes a run waits for and why it is not yours', () => {
    expect(waitingWords(WAIT, NOW)).toEqual({ name: 'An Approver’s yes on Software watchlist', sub: 'You started it · Today 10:14', to: '/runs/run_01JB8' })
    expect(waitingWords({ ...WAIT, trigger: 'schedule' }, NOW).sub).toBe('Your schedule started it · Today 10:14')
    expect(waitingWords({ ...WAIT, because: 'retried' }, NOW).sub).toBe('You retried it · Today 10:14')
    expect(waitingWords({ ...WAIT, because: 'owns' }, NOW).sub).toBe('It is your workflow · Today 10:14')
    expect(waitingWords({ ...WAIT, because: 'decided_earlier', step: 2, steps: 3 }, NOW)).toMatchObject({
      name: 'Another Approver’s yes on Software watchlist',
      sub: 'You already said yes to an earlier step · Today 10:14',
    })
  })

  it('names a draft, or calls it New workflow, with its step and when it was saved', () => {
    const [draft] = ALICE.drafts
    expect(draftWords(draft!, NOW)).toEqual({ name: 'Nudge stale tickets', sub: 'Step 2 of 4. Last saved Wed 4 Nov, 14:24.' })
    expect(draftWords({ ...draft!, name: null }, NOW).name).toBe('New workflow')
  })

  it('names what runs next and where it opens, and how many more are scheduled', () => {
    expect(comingUpOf(BOB, NOW)).toEqual({ name: 'Software watchlist', to: '/software', when: 'Mon 9 Nov, 9:00', more: 0 })
    expect(comingUpOf({ ...BOB, coming_up: { ...BOB.coming_up!, template: 'agent_cards', more: 2 } }, NOW)).toMatchObject({ to: '/workflows/uc_01JB7', more: 2 })
    expect(comingUpOf(DAY_ONE, NOW)).toBeNull()
  })

  it('gives what runs next in its schedule’s own zone, named when it is not Singapore, as the workflow page does', () => {
    const at = (time_zone: string) => comingUpOf({ ...BOB, coming_up: { ...BOB.coming_up!, next_run_at: '2026-11-03T09:00:00Z', time_zone } }, NOW)?.when
    expect(at('Europe/London')).toBe('Today, 9:00 London time')
    expect(at('Asia/Singapore')).toBe('Today, 17:00')
    expect(at('Factory'), 'a zone the browser cannot read').toBe('Today, 17:00 Singapore time')
  })
})
