import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import dayOne from '../../../../contracts/fixtures/builder/home.day-one.json'
import declinedTest from '../../../../contracts/fixtures/builder/home.alice.declined-test.json'
import questionForAlice from '../../../../contracts/fixtures/builder/home.alice.question.json'
import type { AddressItem, ApprovalItem, ConnectionItem, FollowingUpItem, HomeOut, ReplyView, StoppedItem, WaitingItem } from '../../api/types'
import { ApiError } from '../../api/client'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import type { CapabilitiesView } from '../../api/types'
import { actionsOf, approverHeading, approverLine, draftWords, groupOf, HOME_NEEDS_SHOWN, lineOf, moreWords, needsOf, needsTotal, openPathOf, panelItemOf, pinnedOf, retryProblem, suggestionsOf, waitingWords, wordsOf, type Need } from './home'

const BOB = bobHome as HomeOut
const ALICE = aliceHome as HomeOut
const DAY_ONE = dayOne as HomeOut
const DECLINED_TEST = declinedTest as HomeOut
const QUESTION_FOR_ALICE = questionForAlice as HomeOut
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
  it('puts stopped runs first, then approvals, then confirmations', () => {
    const home: HomeOut = { ...BOB, stopped: [STOP], stopped_total: 1 }
    expect(needsOf(home).shown.map((need) => need.kind)).toEqual(['stopped', 'approval', 'confirmation', 'confirmation'])
  })

  it('puts a connection that needs attention after approvals and before confirmations, counts it, and checks it again in place', () => {
    const connection = (ALICE.connections as [ConnectionItem])[0]
    const home: HomeOut = { ...BOB, connections: [connection], stopped: [STOP], stopped_total: 1, replied: [(ALICE.replied as [FollowingUpItem])[0]] }
    const needs = needsOf(home)
    expect(needs.shown.map((need) => need.kind)).toEqual(['stopped', 'approval', 'connection', 'reply', 'confirmation', 'confirmation'])
    expect(needs.total).toBe(needsTotal(home))
    const need = needs.shown.find((item) => item.kind === 'connection') as Need
    expect(actionsOf(need)).toEqual([{ kind: 'open', label: 'See it in Settings', to: '/settings?tab=connections' }])
    expect(wordsOf(need, NOW).title).toBe('Jira is not answering.')
  })

  it('words the platform’s no AI model row as the prototype does, in Do now, with Connect a model and Open going there', () => {
    const model: ConnectionItem = { id: 'model', name: 'AI model', state: 'not_set_up', problem: 'No AI model is turned on.', fix: 'Add an AI model under Settings, AI model.', checked_at: null, last_ok_at: null, expires_at: null }
    const home: HomeOut = { ...BOB, approvals: [], approvals_total: 0, confirmations: [], connections: [model] }
    const [need] = needsOf(home).shown as [Need]
    expect(groupOf(need)).toBe('now')
    expect(keys(needsOf({ ...ALICE, connections: [...ALICE.connections, model] }).shown)[0], 'it leads the list, as nothing that needs it can run').toBe('connection:model')
    const words = wordsOf(need, NOW)
    expect([words.title, words.meta]).toEqual(['No AI model connected', 'Settings, AI model'])
    expect(words.note).toContain('the Planner can’t read new requests')
    expect(actionsOf(need)).toEqual([{ kind: 'open', label: 'Connect a model', to: '/settings?tab=model' }])
    expect(openPathOf(need)).toBe('/settings?tab=model')
    expect(pinnedOf(home)).toEqual({ need, more: 0 })
  })

  it('puts a moved or missing repository after the connections, counts it, and opens that software’s own page', () => {
    const [moved, lost] = ALICE.addresses as [AddressItem, AddressItem]
    const home: HomeOut = { ...BOB, connections: [(ALICE.connections as [ConnectionItem])[0]], addresses: [moved, lost], stopped: [STOP], stopped_total: 1 }
    const needs = needsOf(home)
    expect(needs.shown.map((need) => need.kind)).toEqual(['stopped', 'approval', 'connection', 'address', 'address', 'confirmation', 'confirmation'])
    expect(needs.total).toBe(needsTotal(home))
    const [first, second] = needs.shown.filter((need) => need.kind === 'address') as [Need, Need]
    expect(actionsOf(first)).toEqual([{ kind: 'open', label: 'Show it on the watchlist', to: `/software/${moved.software_id}` }])
    expect(wordsOf(first, NOW).title).toBe('GitHub moved FastAPI from tiangolo/fastapi to fastapi/fastapi.')
    expect(wordsOf(second, NOW).title).toBe('GitHub can’t find langchain-ai/langserve, the address saved for LangServe.')
  })

  it('puts a reply from the team last of Do now, before the Set up group, and counts it', () => {
    const reply = (ALICE.replied as [FollowingUpItem])[0]
    const home: HomeOut = { ...BOB, replied: [reply], stopped: [STOP], stopped_total: 1 }
    expect(needsOf(home).shown.map((need) => need.kind)).toEqual(['stopped', 'approval', 'reply', 'confirmation', 'confirmation'])
    expect(needsTotal(home)).toBe(1 + BOB.approvals_total + BOB.confirmations.length + 1)
  })

  it('orders replies newest reply first and gives each a link to its request', () => {
    const [first] = ALICE.replied as [FollowingUpItem]
    const older: FollowingUpItem = { ...first, request_id: 'trq_old', latest_reply: { ...(first.latest_reply as ReplyView), replied_at: '2026-11-03T08:30:00Z' } }
    const needs = needsOf({ ...DAY_ONE, replied: [older, first] })
    expect(keys(needs.shown)).toEqual(['reply:trq_01JD5RP', 'reply:trq_old'])
    expect(actionsOf(needs.shown[0] as Need)).toEqual([{ kind: 'open', label: 'Read the reply', to: '/workflows?request=trq_01JD5RP' }])
  })

  it('names who replied and quotes the reply, cut short when it is long', () => {
    const [first] = ALICE.replied as [FollowingUpItem]
    const long: FollowingUpItem = { ...first, latest_reply: { ...(first.latest_reply as ReplyView), text: 'x'.repeat(300) } }
    const words = wordsOf(needsOf({ ...DAY_ONE, replied: [first] }).shown[0] as Need, NOW)
    expect(words.title).toBe('Bob replied to your report')
    expect(words.note).toBe('Looking into it.')
    expect(wordsOf(needsOf({ ...DAY_ONE, replied: [long] }).shown[0] as Need, NOW).note).toHaveLength(160)
  })

  it('shows the newest first within each kind, whatever order they came in', () => {
    const home: HomeOut = {
      ...DAY_ONE,
      approvals: [ask('run_old', '2026-11-01T01:00:00Z'), ask('run_new', '2026-11-03T01:00:00Z'), ask('run_mid', '2026-11-02T01:00:00Z')],
      approvals_total: 3,
      stopped: [stop('run_s1', '2026-11-01T01:00:00Z'), stop('run_s2', '2026-11-02T01:00:00Z')],
      stopped_total: 2,
    }
    expect(keys(needsOf(home).shown)).toEqual(['stopped:run_s2', 'stopped:run_s1', 'approval:apr_run_new', 'approval:apr_run_mid', 'approval:apr_run_old'])
  })

  it('keeps the same order for the same moment, so a refresh never swaps two rows', () => {
    const same = '2026-11-03T01:00:00Z'
    const once = needsOf({ ...DAY_ONE, approvals: [ask('run_b', same), ask('run_a', same)], approvals_total: 2 })
    const again = needsOf({ ...DAY_ONE, approvals: [ask('run_a', same), ask('run_b', same)], approvals_total: 2 })
    expect(keys(once.shown)).toEqual(keys(again.shown))
  })

  it('shows everything the platform returned, and counts what it left out from its totals', () => {
    const approvals = Array.from({ length: 10 }, (_, n) => ask(`run_${String(n).padStart(2, '0')}`, `2026-11-03T01:${String(n).padStart(2, '0')}:00Z`))
    const home: HomeOut = { ...BOB, approvals, approvals_total: 50, stopped: [STOP], stopped_total: 1 }
    const needs = needsOf(home)
    expect(needs.shown).toHaveLength(10 + 1 + BOB.confirmations.length)
    expect(needs.shown[0]?.key).toBe('stopped:run_01JB9')
    expect(needs.total).toBe(53)
    expect(needs.more).toEqual({ approvals: 40, others: 0 })
  })

  it(`shows ${HOME_NEEDS_SHOWN} on Home with the most urgent first, and counts the same total`, () => {
    const approvals = Array.from({ length: 7 }, (_, n) => ask(`run_${n}`, `2026-11-03T01:0${n}:00Z`))
    const home: HomeOut = { ...BOB, approvals, approvals_total: 7, stopped: [STOP], stopped_total: 1 }
    const onHome = needsOf(home, HOME_NEEDS_SHOWN)
    expect(HOME_NEEDS_SHOWN, 'Home shows up to five rows, then “N more”').toBe(5)
    expect(keys(onHome.shown)).toEqual(['stopped:run_01JB9', 'approval:apr_run_6', 'approval:apr_run_5', 'approval:apr_run_4', 'approval:apr_run_3'])
    expect(onHome.total).toBe(needsOf(home).total)
    expect(onHome.total).toBe(needsTotal(home))
  })

  it('says nothing more when everything fits', () => {
    expect(needsOf(BOB).more).toEqual({ approvals: 0, others: 0 })
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
    expect(actionsOf(approval)).toEqual([{ kind: 'open', label: 'Review and decide', to: '/runs/run_01JB8', item: { kind: 'run', id: 'run_01JB8' } }])
  })

  it('sends a confirmation to its Settings tab', () => {
    expect(actionsOf(approver)).toEqual([{ kind: 'open', label: 'Review in Settings', to: '/settings?tab=people' }])
    expect(actionsOf(address)).toEqual([{ kind: 'open', label: 'Review in Settings', to: '/settings?tab=model' }])
  })

  it('retries a stopped run the platform can retry, and otherwise opens it', () => {
    expect(actionsOf(stopped)).toEqual([
      { kind: 'retry', label: 'Retry the run', runId: 'run_01JB9' },
      { kind: 'open', label: 'See the run', to: '/runs/run_01JB9', item: { kind: 'run', id: 'run_01JB9' } },
    ])
    const final = { ...stopped, item: { ...STOP, retryable: false } } as Need
    expect(actionsOf(final)).toEqual([{ kind: 'open', label: 'See why it stopped', to: '/runs/run_01JB9', item: { kind: 'run', id: 'run_01JB9' } }])
  })

  it('waits for the model instead of offering a retry that would fail again, and says so', () => {
    expect(actionsOf(stopped, true)).toEqual([{ kind: 'open', label: 'See the run', to: '/runs/run_01JB9', item: { kind: 'run', id: 'run_01JB9' } }])
    expect(wordsOf(stopped, NOW, true).note).toBe('Can run again once an AI model is connected.')
    expect(wordsOf(stopped, NOW).note).toBeNull()
    const final = { ...stopped, item: { ...STOP, retryable: false } } as Need
    expect(actionsOf(final, true)).toEqual(actionsOf(final))
    expect(wordsOf(final, NOW, true).note).toBeNull()
  })
})

describe('a test run an Approver declined', () => {
  const [need] = needsOf(DECLINED_TEST).shown as [Need]

  it('is in its starter’s Do now, counted with the rest', () => {
    expect(need.kind).toBe('declined')
    expect(groupOf(need)).toBe('now')
    expect(needsTotal(DECLINED_TEST)).toBe(1)
  })

  it('says who declined it and gives the rest of the declined record, with the reason, beside an X', () => {
    const words = wordsOf(need, NOW)
    expect(words.tone).toBe('off')
    expect(words.title).toBe('Bob declined your test run')
    expect(words.meta).toMatch(/^Weekly closed-ticket summary · /)
    expect(words.note).toBe('Nothing was written. Reason: Something in it is wrong.')
  })

  it('opens the run, in the side panel from the chat, and offers a new test run of its workflow', () => {
    expect(actionsOf(need)).toEqual([
      { kind: 'open', label: 'See the run', to: '/runs/run_01JD7TS', item: { kind: 'run', id: 'run_01JD7TS' } },
      { kind: 'test', label: 'Do a test run again', useCaseId: 'uc_01JD7TS' },
    ])
    expect(openPathOf(need)).toBe('/runs/run_01JD7TS')
  })

  it('with no AI model offers only the run, and says when a test can start again', () => {
    expect(actionsOf(need, true).map((action) => action.label)).toEqual(['See the run'])
    expect(wordsOf(need, NOW, true).note).toBe('Nothing was written. Reason: Something in it is wrong. A test run can start again once an AI model is connected.')
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

describe('what you wait on, and your drafts', () => {
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
})

describe('the Approver’s heading', () => {
  it('tells an Approver how many changes wait for his yes, in the sketch’s words, and his heading says the same with no full stop', () => {
    expect(approverLine({ ...BOB, confirmations: [], approvals_total: 1 })).toBe('1 change waits for your yes.')
    expect(approverLine({ ...BOB, confirmations: [], approvals_total: 5 })).toBe('5 changes wait for your yes.')
    expect(approverLine({ ...BOB, approvals: [], approvals_total: 0, confirmations: [] })).toBe('Nothing waits for your yes.')
    expect(approverLine(BOB), 'a request and two confirmations').toBe('3 things need you.')
    expect(approverHeading({ ...BOB, confirmations: [], approvals_total: 1 })).toBe('1 change waits for your yes')
    expect(approverHeading({ ...BOB, approvals: [], approvals_total: 0, confirmations: [] })).toBe('Nothing waits for your yes')
  })
})

describe('the three suggestions under the box', () => {
  const CAPS = capabilities as CapabilitiesView

  it('with nothing watched are the platform’s own examples, where the question is an intent and the task is typed words', () => {
    const chips = suggestionsOf(0, CAPS)
    expect(chips.map((chip) => chip.label)).toEqual(CAPS.examples.map((example) => example.text))
    expect(chips.at(-1)?.ask).toEqual({ intent: 'abilities' })
    expect(chips[0]?.ask).toEqual({ text: CAPS.examples[0]?.text })
    expect(suggestionsOf(0, undefined)).toEqual([])
  })

  it('with software watched are the sketch’s three: what needs me and what it can do never ask the model, and the question lane reads the middle one', () => {
    const chips = suggestionsOf(3, CAPS)
    expect(chips.map((chip) => chip.label)).toEqual(['What needs me?', 'Which software is behind?', 'What can you do?'])
    expect(chips.map((chip) => chip.ask)).toEqual([{ intent: 'needs_me' }, { text: 'Which software has a newer version?' }, { intent: 'abilities' }])
  })

  it('shows none until the watchlist has loaded, so the set never flips', () => {
    expect(suggestionsOf(undefined, CAPS)).toEqual([])
  })
})

describe('Needs you in two groups', () => {
  const [jira, github] = ALICE.connections as [ConnectionItem, ConnectionItem]
  const [moved, lost] = ALICE.addresses as [AddressItem, AddressItem]
  const reply = (ALICE.replied as [FollowingUpItem])[0]
  const everything: HomeOut = { ...BOB, connections: [github, jira], addresses: [moved, lost], stopped: [STOP], stopped_total: 1, replied: [reply] }
  const groups = (home: HomeOut) => needsOf(home).shown.map((need) => `${groupOf(need)}:${need.kind}`)

  it('puts stops, approvals and replies in Do now, and confirmations and moved addresses in Set up', () => {
    const home = needsOf(everything).shown
    const of = (kind: Need['kind']) => home.filter((need) => need.kind === kind).map(groupOf)
    expect(of('stopped')).toEqual(['now'])
    expect(of('approval')).toEqual(['now'])
    expect(of('reply')).toEqual(['now'])
    expect(of('address')).toEqual(['set', 'set'])
    expect(of('confirmation')).toEqual(['set', 'set'])
  })

  it('puts a connection that does not work in Do now, because it stops every run, and a key that works but runs out in Set up', () => {
    expect(jira.state).toBe('not_answering')
    expect(github.state).toBe('working')
    const kinds = needsOf(everything).shown.filter((need) => need.kind === 'connection')
    expect(kinds.map((need) => [need.key, groupOf(need)])).toEqual([
      ['connection:jira', 'now'],
      ['connection:github', 'set'],
    ])
  })

  it('lists Do now before Set up, and keeps the order of urgency inside each group', () => {
    expect(groups(everything)).toEqual([
      'now:stopped',
      'now:approval',
      'now:connection',
      'now:reply',
      'set:connection',
      'set:address',
      'set:address',
      'set:confirmation',
      'set:confirmation',
    ])
  })

  it('cuts Home’s five from the grouped list, so a Set up item never takes a place from a Do now item', () => {
    const home: HomeOut = { ...everything, approvals: [ask('run_a', '2026-11-03T01:00:00Z'), ask('run_b', '2026-11-03T02:00:00Z')], approvals_total: 2 }
    expect(keys(needsOf(home, HOME_NEEDS_SHOWN).shown)).toEqual(['stopped:run_01JB9', 'approval:apr_run_b', 'approval:apr_run_a', 'connection:jira', 'reply:trq_01JD5RP'])
  })
})

describe('the pinned line', () => {
  it('names the first of the grouped needs, and N more is the rest of the same count', () => {
    const pinned = pinnedOf(ALICE)
    expect(pinned?.need.key).toBe('stopped:run_01JB9')
    expect((pinned?.more ?? 0) + 1).toBe(needsTotal(ALICE))
    expect((pinnedOf(BOB)?.more ?? 0) + 1).toBe(needsTotal(BOB))
  })

  it('counts what the platform left out of the lists, so the number is the rail’s', () => {
    const approvals = Array.from({ length: 10 }, (_, n) => ask(`run_${n}`, `2026-11-03T01:0${n}:00Z`))
    const home: HomeOut = { ...BOB, approvals, approvals_total: 50 }
    expect((pinnedOf(home)?.more ?? 0) + 1).toBe(needsTotal(home))
  })

  it('is absent when nothing needs the person', () => {
    expect(pinnedOf(DAY_ONE)).toBeNull()
  })

  it('opens the item’s own page: the run for a stop or a request, Settings for a key, its own page for software', () => {
    const open = (home: HomeOut, key: string) => openPathOf(needsOf(home).shown.find((need) => need.key === key) as Need)
    expect(open(ALICE, 'stopped:run_01JB9')).toBe('/runs/run_01JB9')
    expect(open(BOB, 'approval:apr_01JB8')).toBe('/runs/run_01JB8')
    expect(open(ALICE, 'connection:jira')).toBe('/settings?tab=connections')
    expect(open(ALICE, `address:${(ALICE.addresses[0] as AddressItem).software_id}`)).toBe(`/software/${(ALICE.addresses[0] as AddressItem).software_id}`)
  })
})

describe('a question an Approver asked on a request this person made', () => {
  const [need] = needsOf(QUESTION_FOR_ALICE).shown as [Need]

  it('is in the requester’s Do now, counted with the rest', () => {
    expect(need.kind).toBe('question')
    expect(groupOf(need)).toBe('now')
    expect(needsTotal(QUESTION_FOR_ALICE)).toBe(1)
    expect(pinnedOf(QUESTION_FOR_ALICE)).toEqual({ need, more: 0 })
  })

  it('says who asked about which workflow, that the request still waits, and the question', () => {
    const words = wordsOf(need, NOW)
    expect(words.tone, 'a message for this person, as a reply is, never the approval shield').toBe('info')
    expect(words.title).toBe('Bob asked you about Software watchlist')
    expect(words.meta).toBe('The request is still waiting for a yes')
    expect(words.note).toBe('“Has 1.2.16 been tested with our login service?”')
  })

  it('opens the run to answer it, in the side panel from the chat', () => {
    const run = QUESTION_FOR_ALICE.questions_for_me[0]!.run_id
    expect(actionsOf(need)).toEqual([{ kind: 'open', label: 'Answer Bob', to: `/runs/${run}`, item: { kind: 'run', id: run } }])
    expect(panelItemOf(need)).toEqual({ kind: 'run', id: run })
  })
})

describe('each row of Needs you in a few words', () => {
  const [approval, modelAddress, approver] = needsOf(BOB).shown as [Need, Need, Need]
  const [jira, github] = ALICE.connections as [ConnectionItem, ConnectionItem]
  const [moved, lost] = ALICE.addresses as [AddressItem, AddressItem]
  const need = (home: Partial<HomeOut>): Need => needsOf({ ...DAY_ONE, ...home }).shown[0] as Need
  const SAME_DAY = new Date('2026-11-04T15:00:00+08:00')

  it('leads with what the row is about, then says what happened: a stop with its time, red', () => {
    const stopped = need({ stopped: [STOP], stopped_total: 1 })
    expect(lineOf(stopped, SAME_DAY)).toEqual({ tone: 'err', subject: 'Software watchlist', rest: 'stopped at 10:14', short: 'stopped' })
    expect(lineOf(stopped, NOW).rest).toBe('stopped Wed 4 Nov at 10:14')
  })

  it('says a request needs your yes, amber, as the Approver’s row does in the sketch', () => {
    expect(lineOf(approval, NOW)).toEqual({ tone: 'wait', subject: 'Software watchlist', rest: 'needs your yes', short: 'needs your yes' })
  })

  it('names a connection that doesn’t work in red, and a key that runs out with its day, amber', () => {
    expect(jira.state).toBe('not_answering')
    expect(lineOf(need({ connections: [jira] }), NOW)).toEqual({ tone: 'err', subject: 'Jira', rest: 'isn’t answering', short: 'isn’t answering' })
    expect(lineOf(need({ connections: [github] }), NOW)).toEqual({ tone: 'wait', subject: 'GitHub key', rest: 'expires Wed 18 Nov', short: 'expires Wed 18 Nov' })
    expect(lineOf(need({ connections: [{ ...github, expires_at: '2026-11-03T12:00:00Z' }] }), NOW).rest).toBe('expires today')
    const model = { id: 'model', name: 'AI model', state: 'not_set_up', problem: null, fix: null, checked_at: null, last_ok_at: null, expires_at: null } as const
    expect(lineOf(need({ connections: [model] }), NOW)).toMatchObject({ tone: 'err', subject: 'AI model', rest: 'isn’t set up' })
  })

  it('says software can’t be found on GitHub, or where it moved, amber, under Set up', () => {
    expect(lineOf(need({ addresses: [lost] }), NOW)).toEqual({ tone: 'wait', subject: 'LangServe', rest: 'can’t be found on GitHub', short: 'not found' })
    expect(lineOf(need({ addresses: [moved] }), NOW)).toEqual({ tone: 'wait', subject: 'FastAPI', rest: 'moved to fastapi/fastapi on GitHub', short: 'moved' })
  })

  it('names who waits to be confirmed, and a new AI model address', () => {
    expect(lineOf(approver, NOW)).toEqual({ tone: 'wait', subject: 'Dave', rest: 'waits to be confirmed as an Approver', short: 'waits to be confirmed' })
    expect(lineOf(modelAddress, NOW)).toEqual({ tone: 'wait', subject: 'A new AI model address', rest: 'waits to be confirmed', short: 'waits to be confirmed' })
  })

  it('names who declined a test run, who asked a question and who replied, never claiming a write', () => {
    const [declined] = needsOf(DECLINED_TEST).shown as [Need]
    expect(lineOf(declined, NOW)).toEqual({ tone: 'wait', subject: 'Bob', rest: 'declined your test run of Weekly closed-ticket summary', short: 'declined your test run' })
    const [question] = needsOf(QUESTION_FOR_ALICE).shown as [Need]
    expect(lineOf(question, NOW)).toEqual({ tone: 'wait', subject: 'Bob', rest: 'asked you about Software watchlist', short: 'asked you a question' })
    const reply = need({ replied: ALICE.replied })
    expect(lineOf(reply, NOW)).toEqual({ tone: 'wait', subject: 'Bob', rest: 'replied to your report', short: 'replied' })
  })
})
