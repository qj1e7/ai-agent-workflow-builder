import { describe, expect, it } from 'vitest'
import { PRODUCT } from '../../shell/product'
import rejectedView from '@contracts/fixtures/views/rejected.final.json'
import type { ApprovalStepView, RunViewOf } from '../../api/types'
import type { LiveRun } from './liveRun'
import type { ChatItem } from './runModel'
import { declinedBy, declinedNext, declinedNowWords, declinedOfSteps, declinedRecord, declinedWithNext, declineTail, feedTroubleOf, lineOf, runPill, scheduleShort, speakerName, stageWords, type StageFacts } from './words'

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
