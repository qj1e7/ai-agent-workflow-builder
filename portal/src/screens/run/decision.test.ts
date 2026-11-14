import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import { describe, expect, it } from 'vitest'
import type { ApprovalStepView, ApprovalView } from '../../api/types'
import {
  approvalPill,
  approvalTitle,
  cardStatusWords,
  kindWords,
  leadWords,
  recordWords,
  turnWords,
  waitingWords,
  whereWords,
  whyYouWords,
} from './approvalWords'
import { APPROVE, decisionFor, declineReasons, standingOf, stepsAfter, type Standing } from './decision'
import { factsOf } from './words'

const BOB = bob as ApprovalView
const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id
const QUICK = declineReasons('software_watchlist')
/** 9:04 and 9:01 in Singapore, on the day NOW is. */
const AT = '2026-11-03T01:04:00Z'
const EARLIER = '2026-11-03T01:01:00Z'
const NOW = new Date('2026-11-03T10:00:00+08:00')

const step = (index: number, status: ApprovalStepView['status'], decided_by: string | null = null, decided_at: string | null = null, reason: string | null = null): ApprovalStepView => ({
  index,
  label: `Step ${String(index)}`,
  status,
  decided_by,
  decided_at,
  reason,
})

describe('where a request stands, from its steps', () => {
  it('is open at its one step while it waits', () => {
    expect(standingOf(BOB.steps)).toEqual({ is: 'open', step: 0, steps: 1, approvedBy: [] })
  })

  it('is open at the second of two once the first said yes, and names who did', () => {
    expect(standingOf([step(0, 'approved', 'carol', EARLIER), step(1, 'open')])).toEqual({ is: 'open', step: 1, steps: 2, approvedBy: ['carol'] })
  })

  it('is approved only when every step said yes, with each yes in order and the last one’s time', () => {
    expect(standingOf([step(0, 'approved', 'carol', EARLIER), step(1, 'approved', 'bob', AT)])).toEqual({ is: 'approved', by: ['carol', 'bob'], at: AT })
  })

  it('is declined with its record, the reason and any yes before it', () => {
    expect(standingOf([step(0, 'declined', 'bob', AT, 'Not this week')])).toEqual({ is: 'declined', record: { by: 'bob', approvedBy: [], reason: 'Not this week' }, at: AT })
    expect(standingOf([step(0, 'approved', 'carol', EARLIER), step(1, 'declined', 'bob', AT, null), step(2, 'waiting')])).toMatchObject({
      is: 'declined',
      record: { by: 'bob', approvedBy: ['carol'], reason: null },
    })
  })

  it.each([
    ['expired', 'expired'],
    ['cancelled', 'cancelled'],
  ] as const)('is %s when nobody decided in time, and offers no decision', (status, is) => {
    expect(standingOf([step(0, status)])).toEqual({ is })
    expect(standingOf([step(0, 'approved', 'carol', EARLIER), step(1, status)])).toEqual({ is })
  })
})

describe('the steps right after this person decided, before the platform’s next read', () => {
  it('folds a yes on the first of two in, which leaves the second open', () => {
    const steps = stepsAfter([step(0, 'open'), step(1, 'waiting')], { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })
    expect(standingOf(steps)).toEqual({ is: 'open', step: 1, steps: 2, approvedBy: ['bob'] })
  })

  it('folds a decline in, with its reason', () => {
    const steps = stepsAfter(BOB.steps, { step: 0, by: 'bob', verdict: 'decline', at: AT, reason: 'Wrong version' })
    expect(standingOf(steps)).toEqual({ is: 'declined', record: { by: 'bob', approvedBy: [], reason: 'Wrong version' }, at: AT })
  })

  it('keeps what the platform says once it has caught up', () => {
    const read = [step(0, 'declined', 'carol', EARLIER, null)]
    expect(stepsAfter(read, { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })).toBe(read)
  })
})

describe('what a decision posts', () => {
  it('sends the open step and the digest Bob is looking at, and a reason only with a decline', () => {
    expect(decisionFor(BOB, APPROVE)).toEqual({ step: 0, verdict: 'approve', digest: BOB.digest })
    expect(decisionFor(BOB, { verdict: 'decline', reason: 'Not this week' })).toEqual({ step: 0, verdict: 'decline', digest: BOB.digest, reason: 'Not this week' })
    expect(decisionFor(BOB, { verdict: 'decline', reason: null })).not.toHaveProperty('reason')
  })

  it('sends nothing on an expired, cancelled or decided request, even when an old read still says Bob may decide', () => {
    for (const status of ['expired', 'cancelled', 'approved', 'declined'] as const) {
      expect(decisionFor({ ...BOB, steps: [step(0, status, 'carol', EARLIER)] }, APPROVE), status).toBeNull()
    }
  })
})

describe('the request’s words', () => {
  const open: Standing = { is: 'open', step: 0, steps: 1, approvedBy: [] }
  const first: Standing = { is: 'open', step: 0, steps: 2, approvedBy: [] }
  const second: Standing = { is: 'open', step: 1, steps: 2, approvedBy: ['carol'] }

  it('heads it with what will be written, in the sketch’s words', () => {
    expect(approvalTitle(BOB.actions)).toBe('Create 1 Jira ticket')
    expect(approvalTitle([...BOB.actions, ...BOB.actions])).toBe('Create 2 Jira tickets')
    const [ticket] = BOB.actions
    if (!ticket) throw new Error('the fixture has one action')
    expect(approvalTitle([{ ...ticket, operation: 'add_comment' }])).toBe('Write 1 change in Jira')
    expect(approvalTitle([ticket, { ...ticket, connector: 'confluence', operation: 'update_page' }])).toBe('Write 2 changes')
  })

  it('says whose workflow asked, and where each ticket goes, naming the Jira before the yes', () => {
    expect(kindWords(BOB, nameOf)).toBe('Approval, from Alice’s Software watchlist')
    const [ticket] = BOB.actions
    if (!ticket) throw new Error('the fixture has one action')
    expect(whereWords(ticket)).toBe('Jira project MOCK on the practice Jira')
    expect(whereWords({ ...ticket, site_name: 'jira.example.com' })).toBe('Jira project MOCK on jira.example.com')
  })

  it.each([
    ['Bob, who may decide', open, true, 'Needs your yes', 'wait'],
    ['Alice, whose work it is', open, false, 'Waiting for a yes', 'wait'],
    ['anyone, once approved', { is: 'approved', by: ['bob'], at: AT }, false, 'Approved', 'ok'],
    ['anyone, once declined', { is: 'declined', record: { by: 'bob', approvedBy: [], reason: null }, at: AT }, false, 'Declined', 'quiet'],
    ['anyone, once nobody answered', { is: 'expired' }, true, 'No answer', 'quiet'],
    ['anyone, once the workflow went', { is: 'cancelled' }, true, 'Cancelled', 'quiet'],
  ] as const)('gives %s one pill', (_who, standing, can, label, tone) => {
    expect(approvalPill(standing, can)).toEqual({ label, tone })
  })

  it('keeps the two Approvers’ words: step 1 of 2, then step 2 of 2 after the first yes', () => {
    expect(turnWords(open, nameOf)).toBeNull()
    expect(turnWords(first, nameOf)).toBe('Step 1 of 2. It needs two Approvers, one after the other.')
    expect(turnWords(second, nameOf)).toBe('Step 2 of 2. Carol said yes first.')
    expect(whyYouWords(open, nameOf)).toBe('No one can approve their own work.')
    expect(whyYouWords(first, nameOf)).toBe('No one can approve their own work. Your yes is the first of two.')
    expect(whyYouWords(second, nameOf)).toBe('Carol said yes. Your yes is the second of two.')
  })

  it('tells someone who can’t decide why, in a line where the buttons would be', () => {
    expect(waitingWords('own_work')).toBe('Waiting for an Approver. You can’t approve your own work.')
    expect(waitingWords('decided_earlier_step')).toBe('Waiting for another Approver. You said yes to the step before, and no one says yes twice.')
    expect(waitingWords('not_an_approver')).toBe('Waiting for an Approver. Only an Approver can decide.')
    expect(waitingWords(null)).toBe('Waiting for an Approver.')
  })

  it('leads the cards with the sketch’s line', () => {
    expect(leadWords(1)).toBe('This needs your yes.')
    expect(leadWords(3)).toBe('These need your yes.')
  })

  describe('the record', () => {
    const approved: Standing = { is: 'approved', by: ['bob'], at: AT }
    const record = (standing: Standing, facts = factsOf('acting', { count: 1 })) => recordWords(standing, facts, nameOf, QUICK, NOW)

    it('says nothing while the request waits', () => {
      expect(record(open)).toBeNull()
    })

    it('says who approved and when, then what the run is doing, then what it wrote', () => {
      expect(record(approved)).toBe('Approved by Bob at 9:04. Creating the ticket…')
      expect(record(approved, factsOf('awaiting_approval', { count: 1 })), 'the run’s own events lag').toBe('Approved by Bob at 9:04. Creating the ticket…')
      expect(record(approved, factsOf('succeeded', { count: 1, refs: ['MOCK-22'] }))).toBe('Approved by Bob at 9:04. MOCK-22 created.')
      expect(record(approved, factsOf('succeeded', { count: 2 }))).toBe('Approved by Bob at 9:04. 2 tickets created.')
      expect(record(approved, factsOf('lost'))).toBe('Approved by Bob at 9:04. n8n lost the run. Nothing was written.')
      expect(recordWords(approved, null, nameOf, QUICK, NOW), 'with no run to read').toBe('Approved by Bob at 9:04.')
    })

    it('names both Approvers in turn', () => {
      expect(record({ is: 'approved', by: ['carol', 'bob'], at: AT })).toBe('Approved by Carol, then Bob at 9:04. Creating the ticket…')
    })

    it('says the day when it was not today', () => {
      expect(recordWords(approved, null, nameOf, QUICK, new Date('2026-11-05T10:00:00+08:00'))).toBe('Approved by Bob on Tue 3 Nov at 9:04.')
    })

    it('reads a quick reason on in the sentence, keeps a typed one as typed, and never says created', () => {
      const declined = (reason: string | null, approvedBy: readonly string[] = []): Standing => ({ is: 'declined', record: { by: 'bob', approvedBy, reason }, at: AT })
      expect(record(declined('Not this week'))).toBe('Declined by Bob at 9:04: not this week. Nothing was written.')
      expect(record(declined('The login service breaks on 1.2.16'))).toBe('Declined by Bob at 9:04: The login service breaks on 1.2.16. Nothing was written.')
      expect(record(declined(null))).toBe('Declined by Bob at 9:04. Nothing was written.')
      expect(record(declined(null, ['carol']))).toBe('Approved by Carol, then declined by Bob at 9:04. Nothing was written.')
      expect(record(declined('Wrong version'), factsOf('succeeded', { count: 1, refs: ['MOCK-22'] }))).not.toMatch(/created/)
    })

    it('says why nobody can decide an expired or cancelled request', () => {
      expect(record({ is: 'expired' })).toBe('No one said yes in time. Nothing was written, and it can’t be decided now.')
      expect(record({ is: 'cancelled' })).toBe('The workflow was deleted before anyone decided. Nothing was written, and it can’t be decided now.')
    })
  })

  it('gives the chat’s card the short record at the left of its foot', () => {
    expect(cardStatusWords({ is: 'open', step: 0, steps: 1, approvedBy: [] }, null)).toBeNull()
    expect(cardStatusWords({ is: 'approved', by: ['bob'], at: AT }, factsOf('acting', { count: 1 }))).toBe('Approved.')
    expect(cardStatusWords({ is: 'approved', by: ['bob'], at: AT }, factsOf('succeeded', { count: 1, refs: ['MOCK-22'] }))).toBe('Approved. MOCK-22 created.')
    expect(cardStatusWords({ is: 'declined', record: { by: 'bob', approvedBy: [], reason: 'Not this week' }, at: AT }, null)).toBe('Declined. Nothing was written.')
    expect(cardStatusWords({ is: 'expired' }, null)).toBe('No answer. Nothing was written.')
    expect(cardStatusWords({ is: 'cancelled' }, null)).toBe('Cancelled. Nothing was written.')
  })
})
