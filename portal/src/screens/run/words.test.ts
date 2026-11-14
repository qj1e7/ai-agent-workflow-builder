import { describe, expect, it } from 'vitest'
import { PRODUCT } from '../../shell/product'
import rejectedView from '@contracts/fixtures/views/rejected.final.json'
import type { ApprovalStepView, RunViewOf } from '../../api/types'
import type { LiveRun } from './liveRun'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { emptyModel, foldWire, type ChatItem, type RunModel } from './runModel'
import { stageAnswers } from './stageAnswers'
import { declinedBy, declinedNext, declinedNowWords, declinedOfSteps, declinedRecord, declinedWithNext, declineTail, feedTroubleOf, lineOf, logRowsOf, runKind, runPill, scheduleShort, speakerName, stageFactsOf, stageWords, type StageFacts } from './words'

describe('the run chat', () => {
  it('names the app by its full name', () => {
    expect(speakerName({ kind: 'app' })).toBe(PRODUCT)
    expect(PRODUCT).toBe('AI Workflow Builder')
  })
})

describe('a run page whose live feed has not brought the first events', () => {
  it('waits quietly while it connects', () => {
    expect(feedTroubleOf({ is: 'connecting' }, 'dev')).toEqual({ kind: 'loading' })
  })

  it('says it is trying again while it reconnects', () => {
    expect(feedTroubleOf({ is: 'reconnecting', attempt: 3, inMs: 2000 }, 'dev')).toEqual({ kind: 'waiting', words: 'Can’t reach the platform yet. Trying again.' })
  })

  it.each([
    [404, 'not_found', 'dev', { kind: 'stop', heading: 'Run not found', lead: 'There is no run at this address.' }],
    [403, 'forbidden', 'dev', { kind: 'stop', heading: 'You can’t see this run', lead: 'This account does not have access to it.' }],
    [401, 'signed_out', 'dev', { kind: 'stop', heading: 'You’re signed out', lead: 'Sign in as one of the demo users, then open the run again.' }],
    [401, 'signed_out', 'oidc', { kind: 'stop', heading: 'You’re signed out', lead: 'Sign in again, then open the run again.' }],
    [0, 'rejected', 'dev', { kind: 'retry', heading: 'We couldn’t load this run', lead: 'Check your connection, or try again in a moment.' }],
  ] as const)('says why when the platform answers %i', (status, reason, signIn, trouble) => {
    const closed: LiveRun['connection'] = { is: 'closed', status, reason }
    expect(feedTroubleOf(closed, signIn)).toEqual(trouble)
  })
})

describe('a Tell in the run\'s chat', () => {
  const nameOf = (id: string) => id
  const told = (line: string, bad: boolean): ChatItem => ({ kind: 'told', seq: 1, at: 0 as ChatItem['at'], line, bad })

  it('is the platform saying what it sent, or why nothing was, in its own words', () => {
    const would = 'Would have posted to CODESparks Ops and emailed the team\'s list. Nothing was sent in a test run.'
    expect(lineOf(told(would, false), nameOf, null)).toEqual({ speaker: { kind: 'platform' }, text: would, tone: 'plain' })
    expect(lineOf(told('Not confirmed: the Tell flow answered 502. It is not sent again.', true), nameOf, null).tone).toBe('bad')
  })
})

describe('the declined record', () => {
  const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob' })[id] ?? id
  const step = (index: number, change: Partial<ApprovalStepView>): ApprovalStepView => ({ index, label: `Step ${index}`, status: 'open', decided_by: null, decided_at: null, reason: null, ...change })

  it('says who declined, that nothing was written, and why when there is a reason', () => {
    expect(declinedRecord({ by: 'bob', approvedBy: [], reason: 'Wrong version' }, nameOf)).toBe('Declined by Bob. Nothing was written. Reason: Wrong version.')
    expect(declinedRecord({ by: 'bob', approvedBy: [], reason: null }, nameOf)).toBe('Declined by Bob. Nothing was written.')
  })

  it('tells the person who declined, right after, that nothing was written and why, as the prototype’s message does', () => {
    expect(declinedNowWords({ reason: 'Wrong version' })).toBe('Declined. Nothing was written. Reason: Wrong version.')
    expect(declinedNowWords({ reason: null })).toBe('Declined. Nothing was written.')
  })

  it('keeps a first yes, so the record says both', () => {
    expect(declinedRecord({ by: 'alice', approvedBy: ['bob'], reason: 'Not this week' }, nameOf)).toBe('Approved by Bob, then declined by Alice. Nothing was written. Reason: Not this week.')
  })

  it('ends the reason with one full stop, whatever the Approver typed', () => {
    expect(declineTail({ reason: 'Is it tested?' })).toBe('Nothing was written. Reason: Is it tested?')
    expect(declineTail({ reason: 'Wrong version.' })).toBe('Nothing was written. Reason: Wrong version.')
  })

  it('has a short form for a line with room for only who declined', () => {
    expect(declinedBy({ by: 'bob' }, nameOf)).toBe('Declined by Bob')
  })

  it('reads its facts from a request’s steps, the same as the run route gives them', () => {
    const view = rejectedView as RunViewOf<'rejected'>
    expect(declinedOfSteps(view.approval.steps)).toEqual({ by: 'bob', approvedBy: [], reason: 'Wrong version' })
    const second = [step(0, { status: 'approved', decided_by: 'bob' }), step(1, { status: 'declined', decided_by: 'alice', reason: 'Needs testing first' })]
    expect(declinedOfSteps(second)).toEqual({ by: 'alice', approvedBy: ['bob'], reason: 'Needs testing first' })
    expect(declinedOfSteps([step(0, { status: 'approved', decided_by: 'bob' })])).toBeNull()
  })

  it('is the last word of a declined run’s chat, which never says Done', () => {
    const declined: ChatItem = { kind: 'declined', seq: 1, at: 0 as ChatItem['at'], record: { by: 'bob', approvedBy: [], reason: 'Wrong version' } }
    expect(lineOf(declined, nameOf, null).text).toBe('Declined by Bob. Nothing was written. Reason: Wrong version. The run ended.')
    expect(lineOf(declined, nameOf, 'Change what it does, or run the test again.').text).toBe('Declined by Bob. Nothing was written. Reason: Wrong version. The run ended. Change what it does, or run the test again.')
  })

  it('says what happens next only when the platform will do it: a test waits for its owner, a schedule runs again', () => {
    const now = new Date('2026-11-12T12:00:00+08:00')
    const monday = { at: '2026-11-16T01:00:00Z', zone: 'Asia/Singapore' }
    expect(declinedNext({ test: true, watchlist: false }, monday, now)).toBe('Change what it does, or run the test again.')
    expect(declinedNext({ test: false, watchlist: true }, monday, now)).toBe('The tickets will be proposed again at the next check, Mon 16 Nov, 9:00.')
    expect(declinedNext({ test: false, watchlist: false }, monday, now)).toBe('It runs again Mon 16 Nov, 9:00.')
    expect(declinedNext({ test: false, watchlist: true }, null, now), 'nothing is due, so nothing is promised').toBeNull()
  })

  it('puts what happens next after the record, in one sentence each', () => {
    const declined = { by: 'bob', approvedBy: [], reason: 'Wrong version' }
    expect(declinedWithNext(declined, 'Change what it does, or run the test again.', nameOf)).toBe('Declined by Bob. Nothing was written. Reason: Wrong version. Change what it does, or run the test again.')
    expect(declinedWithNext(declined, null, nameOf)).toBe('Declined by Bob. Nothing was written. Reason: Wrong version.')
  })
})

const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob', carol: 'Carol' }
const named = (id: string) => NAMES[id] ?? id
const QUICK = ['Not this week', 'Wrong version', 'Needs testing first']
const replay = (raw: readonly { run_id: string; seq: number }[], upTo = Infinity): RunModel => {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

type Wire = { run_id: string; seq: number; kind?: string; data?: Record<string, unknown> }

/** The same run, updating a Confluence page in place of creating a Jira ticket. */
const pageUpdate = (raw: readonly Wire[]): Wire[] =>
  raw.map((item) => {
    if (item.kind === 'write_action_proposed') return { ...item, data: { ...item.data, actions: [{ connector: 'confluence', operation: 'update_page', line: 'Update the page' }] } }
    if (item.kind === 'write_action_done') return { ...item, data: { ...item.data, connector: 'confluence', operation: 'update_page', external_reference: 'PAGE-7' } }
    return item
  })

/** The same run with two Approvers, one after the other: Carol says yes first, then Bob. */
const twoYeses = (raw: readonly Wire[]): Wire[] =>
  raw
    .flatMap((item): Wire[] => {
      if (item.kind === 'approval_requested') {
        const open = (index: number, label: string) => ({ index, label, status: 'open', decided_by: null, decided_at: null, reason: null })
        return [{ ...item, data: { ...item.data, steps: [open(0, 'First approver'), open(1, 'Second approver')] } }]
      }
      if (item.kind === 'approval_decided') return [{ ...item, data: { ...item.data, by: 'carol' } }, { ...item, data: { ...item.data, step: 1 } }]
      return [item]
    })
    .map((item, index) => ({ ...item, seq: index + 1 }))

describe('a run followed from its own events, in the same stage words', () => {
  const words = (model: RunModel) => stageWords(stageFactsOf(model), named)

  it('reads where a run stands from its events, and calls a run retried after a stop Retrying', () => {
    expect(words(replay(failure))).toBe('An agent could not finish its work')
    expect(words(replay(success, 6))).toBe('Running')
    expect(words(replay(success, 15))).toBe('Waiting for a yes')
    expect(words(replay(success, 18))).toBe('Creating the ticket')
    expect(words(replay(success))).toBe('MOCK-142 created, approved by Bob')
    expect(words(replay(rejected))).toBe('Declined by Bob. Nothing was written.')
    const retried = { ...replay(failure), phase: { state: 'pending' }, chat: [...replay(failure).chat, { kind: 'retried', by: 'alice', seq: 15, at: 0 as ChatItem['at'] }] } as RunModel
    expect(words(retried)).toBe('Retrying')
    expect(runPill(stageFactsOf(retried)), 'a retry runs, as any run at work does').toEqual({ label: 'Running', tone: 'new' })
  })

  it('says what a run writes from what it does, before and after the write lands', () => {
    expect(words(replay(pageUpdate(success), 18))).toBe('Writing the changes')
    expect(words(replay(pageUpdate(success)))).toBe('PAGE-7 written, approved by Bob')
  })

  it('gives the troubleshooter’s Now row in the same words, naming every Approver who said yes', () => {
    const now = (model: RunModel) => stageAnswers(model, '', named).find((answer) => answer.label === 'Now')?.text
    expect(now(replay(success, 6))).toBe('Running…')
    expect(now(replay(success, 15))).toBe('Waiting for a yes.')
    expect(now(replay(success, 18))).toBe('Bob said yes. Creating the ticket…')
    expect(now(replay(pageUpdate(success), 18))).toBe('Bob said yes. Writing the changes…')
    expect(now(replay(twoYeses(success), 19))).toBe('Carol and Bob said yes. Creating the ticket…')
    expect(stageAnswers(replay(success), 'Found 1.2.16.', named)).toEqual([])
  })

  it('never says a declined run wrote anything', () => {
    const facts = stageFactsOf(replay(rejected))
    expect(facts.refs).toEqual([])
    expect(stageWords(facts, named)).not.toMatch(/created|written$/)
  })
})

describe('the first line over a run', () => {
  it('names today’s run by its time, and another day by its day', () => {
    const now = new Date('2026-11-13T05:00:00Z')
    expect(runKind('2026-11-13T00:00:00Z', now)).toBe('Today’s run, 8:00')
    expect(runKind('2026-11-12T00:00:00Z', now)).toBe('Yesterday’s run, 8:00')
    expect(runKind('2026-11-03T00:00:00Z', now)).toBe('Run on Tue 3 Nov, 8:00')
  })
})

describe('the Step by step log', () => {
  const rows = (model: RunModel) => logRowsOf(model.chat, named, QUICK).map((row) => `${row.time} ${row.agent ? `${row.agent.display}: ` : ''}${row.text}`)

  it('tells an approved run in one sentence a row, with the time to the second and no row for who joined or that it finished', () => {
    const told = rows(replay(success))
    expect(told[0]).toBe('10:14:00 Alice started the run.')
    expect(told).toContain('10:14:08 Asked an Approver for a yes in Teams.')
    expect(told).toContain('10:20:23 Bob said yes.')
    expect(told.at(-1)).toBe('10:20:26 Created MOCK-142 in Jira.')
    expect(told.join(' ')).not.toMatch(/joined|Done\./)
  })

  it('keeps what the agents found as its own row, after they spoke and before the ask, once the run is decided too', () => {
    for (const told of [rows(replay(success)), rows(replay(rejected))]) {
      const found = told.indexOf('10:14:05 LangGraph has a new release: 1.2.16.')
      expect(found).toBeGreaterThan(0)
      expect(found).toBeLessThan(told.indexOf('10:14:08 Asked an Approver for a yes in Teams.'))
    }
    expect(rows(replay(failure)).join(' '), 'a run that stopped before the agents finished found nothing').not.toMatch(/new release: 1\.2\.16\.$/)
  })

  it('ends a declined run on the one row that says who declined and that nothing was written', () => {
    const told = rows(replay(rejected))
    expect(told.at(-1)).toBe('10:18:11 Bob declined: wrong version. Nothing was written.')
    expect(told.filter((row) => /declined/.test(row))).toHaveLength(1)
    expect(told.join(' ')).not.toMatch(/created|Created/)
  })

  it('says a stopped run stopped before anything was written', () => {
    expect(rows(replay(failure)).at(-1)).toMatch(/The run stopped\. Nothing was written\.$/)
  })
})

describe('the stage words, one function for the row, the banner, the strip and Recent runs', () => {
  const base: StageFacts = { state: 'succeeded', count: 0, tickets: true, approvedBy: [], declinedBy: null, reason: null }
  const nameOf = (id: string) => ({ bob: 'Bob', alice: 'Alice' })[id] ?? id
  const stage = (change: Partial<StageFacts>) => stageWords({ ...base, ...change }, nameOf)

  it('says why a run stopped, in the failure’s own plain words', () => {
    expect(stage({ state: 'failed', reason: 'AgentError' })).toBe('An agent could not finish its work')
    expect(stage({ state: 'failed' })).toBe('Stopped')
  })

  it('says a run that waits needs a yes, and a run in progress is running', () => {
    expect(stage({ state: 'awaiting_approval', count: 1 })).toBe('Waiting for a yes')
    for (const state of ['pending', 'working', 'proposed'] as const) expect(stage({ state })).toBe('Running')
  })

  it('says what a run that is writing creates', () => {
    expect(stage({ state: 'acting', count: 1 })).toBe('Creating the ticket')
    expect(stage({ state: 'acting', count: 2 })).toBe('Creating the tickets')
    expect(stage({ state: 'acting', count: 2, tickets: false })).toBe('Writing the changes')
  })

  it('says what a finished run wrote and who said yes, and says so when nothing was new', () => {
    expect(stage({ count: 1, approvedBy: ['bob'] })).toBe('1 ticket created, approved by Bob')
    expect(stage({ count: 2, approvedBy: ['bob', 'alice'] })).toBe('2 tickets created, approved by Bob and Alice')
    expect(stage({ count: 1, tickets: false })).toBe('1 change written')
    expect(stage({ count: 0 })).toBe('Nothing new to write')
  })

  it('says a declined run wrote nothing, and never says created', () => {
    expect(stage({ state: 'rejected', declinedBy: 'bob' })).toBe('Declined by Bob. Nothing was written.')
    expect(stage({ state: 'rejected' })).toBe('Declined. Nothing was written.')
  })

  it('says a test run passed and wrote nothing, never that it is done or found nothing new', () => {
    expect(stage({ outcome: 'test_passed' })).toBe('Test run passed up to the yes. Nothing was written.')
    expect(stage({ outcome: 'nothing_to_write', test: true })).toBe('Test run passed. There was nothing new to write.')
    expect(runPill({ ...base, outcome: 'test_passed' })).toEqual({ label: 'Test run passed', tone: 'ok' })
    expect(runPill({ ...base, outcome: 'nothing_to_write', test: true })).toEqual({ label: 'Test run passed', tone: 'ok' })
  })

  it('reads a test run’s outcome from its own events', () => {
    const end = { run_id: 'run_01JB8', seq: 9, ts: '2026-11-03T02:14:06Z', actor: { kind: 'platform', id: 'platform', display: 'Platform' }, summary: '', kind: 'run_succeeded', data: { outcome: 'test_passed' } }
    const passed = foldWire(emptyModel, [...success.slice(0, 8), end], 'run_01JB8')
    expect(stageWords(stageFactsOf(passed), (id) => id)).toBe('Test run passed up to the yes. Nothing was written.')
  })

  it('has one pill for each run state, in the sketch’s words', () => {
    expect(runPill({ ...base, state: 'failed' })).toEqual({ label: 'Stopped', tone: 'bad' })
    expect(runPill({ ...base, state: 'working' })).toEqual({ label: 'Running', tone: 'new' })
    expect(runPill({ ...base, state: 'awaiting_approval' })).toEqual({ label: 'Waiting for a yes', tone: 'wait' })
    expect(runPill({ ...base, count: 1 })).toEqual({ label: 'Done', tone: 'ok' })
    expect(runPill(base)).toEqual({ label: 'Nothing new', tone: 'quiet' })
    expect(runPill({ ...base, state: 'rejected' })).toEqual({ label: 'Declined', tone: 'quiet' })
  })
})

describe('a schedule in few words', () => {
  it('reads Daily 8:00, Weekdays 9:30 or Mon 13:00', () => {
    expect(scheduleShort({ day: 'every_day', at: '08:00' })).toBe('Daily 8:00')
    expect(scheduleShort({ day: 'weekdays', at: '09:30' })).toBe('Weekdays 9:30')
    expect(scheduleShort({ day: 'monday', at: '13:00' })).toBe('Mon 13:00')
  })
})
