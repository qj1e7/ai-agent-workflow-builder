import { describe, expect, it } from 'vitest'
import type { ApprovalActionView, ApprovalStepView } from '../../api/types'
import { decidesLine, foundLine, previewOf, runByWords, statusOf, tenseOf, wantsLine } from './happened'
import { factsOf } from './words'

const NOW = new Date('2026-11-25T10:00:00+08:00')
const NOBODY = { ownsIt: false, startedIt: false, retriedIt: false, schedule: false } as const
const STARTER = { ...NOBODY, ownsIt: true, startedIt: true }
const named = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id

const ticket = (fields: Record<string, unknown>, project = 'MOCK'): ApprovalActionView => ({
  connector: 'jira',
  operation: 'create_ticket',
  target: { project },
  fields,
  site_name: 'the practice Jira',
})

describe('the line of what was found', () => {
  const release = { version: '0.165.0', at: '2026-11-18T08:00:00Z' }

  it('names the software, its newest release and the day it came out, from the run’s own facts', () => {
    expect(foundLine(release, 'FastAPI release check', 'cards', NOW)).toBe('FastAPI 0.165.0 is out (18 Nov).')
  })

  it('leaves the day out when the run did not read one, and never guesses it', () => {
    expect(foundLine({ version: '0.165.0', at: null }, 'FastAPI release check', 'cards', NOW)).toBe('FastAPI 0.165.0 is out.')
  })

  it('adds the year when the release is from another year', () => {
    expect(foundLine({ version: '0.1.0', at: '2025-12-30T08:00:00Z' }, 'FastAPI release check', 'cards', NOW)).toBe('FastAPI 0.1.0 is out (30 Dec 2025).')
  })

  it('says Version when the workflow’s name does not say what software it checks', () => {
    expect(foundLine(release, 'Morning check', 'cards', NOW)).toBe('Version 0.165.0 is out (18 Nov).')
  })

  it('says nothing when no release was read, or when the workflow watches many pieces of software', () => {
    expect(foundLine(null, 'FastAPI release check', 'cards', NOW)).toBeNull()
    expect(foundLine(release, 'Software watchlist', 'software_watchlist', NOW)).toBeNull()
  })
})

describe('what the run wants to do', () => {
  const one = [{ connector: 'jira', operation: 'create_ticket', target: { project: 'MOCK' } }]

  it.each([
    ['wants', 'This run wants to create 1 Jira ticket in MOCK:'],
    ['doing', 'This run is creating 1 Jira ticket in MOCK:'],
    ['did', 'This run created 1 Jira ticket in MOCK:'],
    ['wanted', 'This run wanted to create 1 Jira ticket in MOCK:'],
  ] as const)('says it in the %s tense', (tense, words) => {
    expect(wantsLine(one, tense)).toBe(words)
  })

  it('counts tickets', () => {
    expect(wantsLine([...one, ...one], 'wants')).toBe('This run wants to create 2 Jira tickets in MOCK:')
  })

  it('says a write that is not a ticket as a change, and where', () => {
    expect(wantsLine([{ connector: 'confluence', operation: 'update_page', target: {} }], 'wants')).toBe('This run wants to write 1 change in Confluence:')
  })
})

describe('the ticket as a small preview', () => {
  it('gives the title, then the first line of the text as a one-line gist', () => {
    const preview = previewOf(ticket({ title: 'New FastAPI release 0.165.0', body: 'Links the release notes. Suggests reviewing whether to upgrade.\nMore lines.\nhttps://example.com' }))
    expect(preview).toEqual({ title: 'New FastAPI release 0.165.0', gist: 'Links the release notes. Suggests reviewing whether to upgrade.' })
  })

  it('cuts a long first line at a word, with an ellipsis', () => {
    const body = `${'word '.repeat(40)}end`
    const { gist } = previewOf(ticket({ title: 'T', body }))
    expect(gist?.length).toBeLessThanOrEqual(100)
    expect(gist?.endsWith('…')).toBe(true)
    expect(gist).not.toMatch(/\s…$/)
  })

  it('has no gist when there is no text, and still names the write', () => {
    expect(previewOf(ticket({ title: 'Only a title' }))).toEqual({ title: 'Only a title', gist: null })
    expect(previewOf(ticket({})).title).toBe('Create 1 Jira ticket')
  })
})

describe('who decides, and when they were asked', () => {
  const step = (over: Partial<ApprovalStepView> = {}): ApprovalStepView => ({ index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null, reason: null, post: 'sent', sent_to: [], sent_at: '2026-11-25T02:25:00Z', ...over })

  it('says an Approver decides in Teams, and when they were asked', () => {
    expect(decidesLine({ steps: [step()], canDecide: true, whyNot: null, party: null, now: NOW })).toBe('An Approver decides in Teams (asked 10:25).')
  })

  it('names the day when they were asked on another day', () => {
    expect(decidesLine({ steps: [step({ sent_at: '2026-11-24T02:25:00Z' })], canDecide: true, whyNot: null, party: null, now: NOW })).toBe('An Approver decides in Teams (asked Tue 24 Nov, 10:25).')
  })

  it('tells the person who started the run that they cannot approve it', () => {
    expect(decidesLine({ steps: [step()], canDecide: false, whyNot: 'own_work', party: STARTER, now: NOW })).toBe('An Approver decides in Teams (asked 10:25). You can’t approve your own run.')
  })

  it('says why someone else cannot decide', () => {
    expect(decidesLine({ steps: [step()], canDecide: false, whyNot: 'not_an_approver', party: null, now: NOW })).toBe('An Approver decides in Teams (asked 10:25). Only an Approver can decide.')
  })

  it('does not name a time before the request is in Teams', () => {
    expect(decidesLine({ steps: [step({ post: 'waiting', sent_at: null })], canDecide: true, whyNot: null, party: null, now: NOW })).toBe('An Approver decides in Teams.')
  })

  it('says an Approver can still decide on the page when Teams could not be reached', () => {
    expect(decidesLine({ steps: [step({ post: 'failed', sent_at: null })], canDecide: true, whyNot: null, party: null, now: NOW })).toBe('An Approver decides on this page. Teams could not be reached.')
  })

  it('never says yes as a noun', () => {
    const all = [step(), step({ post: 'failed' }), step({ post: 'waiting' })].map((one) => decidesLine({ steps: [one], canDecide: false, whyNot: 'decided_earlier_step', party: null, now: NOW }))
    expect(all.join(' ')).not.toMatch(/\byes\b/i)
  })
})

describe('the status on the right of the top line', () => {
  const facts = (state: Parameters<typeof factsOf>[0], known: Parameters<typeof factsOf>[1] = {}) => factsOf(state, { count: 1, ...known })

  it.each([
    [facts('awaiting_approval'), 'Waiting for approval', 'wait'],
    [facts('acting', { approvedBy: ['bob'] }), 'Approved by Bob', 'new'],
    [facts('succeeded', { approvedBy: ['bob'], refs: ['MOCK-1'] }), 'Done', 'ok'],
    [facts('rejected', { declinedBy: 'bob' }), 'Declined', 'quiet'],
    [facts('failed'), 'Stopped', 'bad'],
    [facts('working'), 'Running', 'new'],
  ] as const)('says %o as %s', (given, label, tone) => {
    expect(statusOf(given, named)).toEqual({ label, tone })
  })

  it('names both Approvers once two have approved', () => {
    expect(statusOf(facts('acting', { approvedBy: ['carol', 'bob'] }), named).label).toBe('Approved by Carol and Bob')
  })

  it('says Running while a run writes before anyone is named', () => {
    expect(statusOf(facts('acting'), named).label).toBe('Running')
  })
})

describe('who ran it', () => {
  it('names the person, or says it ran on its schedule', () => {
    expect(runByWords('person', 'carol', named)).toBe('run by Carol')
    expect(runByWords('schedule', null, named)).toBe('run on its schedule')
    expect(runByWords('person', null, named)).toBe('run')
  })
})

describe('who may be told they cannot approve their own run', () => {
  const step: ApprovalStepView = { index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null, reason: null, post: 'sent', sent_to: [], sent_at: '2026-11-25T02:25:00Z' }
  const line = (party: Parameters<typeof decidesLine>[0]['party']) => decidesLine({ steps: [step], canDecide: false, whyNot: 'own_work', party, now: NOW })

  it('tells the person who started the run, in those words', () => {
    expect(line(STARTER)).toContain('You can’t approve your own run.')
  })

  it('gives the owner who did not start it, and someone who retried it, their own reason', () => {
    expect(line({ ...NOBODY, ownsIt: true })).toContain('You set this workflow up, so another Approver must decide.')
    expect(line({ ...NOBODY, ownsIt: true })).not.toContain('own run')
    expect(line({ ...NOBODY, retriedIt: true })).toContain('You retried this run, so another Approver must decide.')
  })
})

describe('the tense of what a run wants to do, in every state that holds a request', () => {
  it.each([
    ['awaiting_approval', 'wants'],
    ['acting', 'doing'],
    ['succeeded', 'did'],
    ['rejected', 'wanted'],
    ['expired', 'wanted'],
    ['lost', 'wanted'],
  ] as const)('%s is %s', (state, tense) => {
    expect(tenseOf(state)).toBe(tense)
  })

  it('has none for a run with no request yet', () => {
    expect(tenseOf('working')).toBeUndefined()
    expect(tenseOf('failed')).toBeUndefined()
  })
})
