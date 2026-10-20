import { describe, expect, it } from 'vitest'
import { agentId, doorKey, runTime, type ApprovalStep, type Ticket } from '../run'
import { checkerStatus, doorName, splitActionLine, stepStatus, writeDoorAction, writeDoorLine, writeDoorStatus } from './words'

const OPEN: ApprovalStep = { index: 0, label: 'Team approver', state: { is: 'open', since: runTime(0) } }

describe('the open seat', () => {
  it('counts the wait to the second, says sped up without the seconds at wide, and never breaks inside the duration at compact', () => {
    expect(stepStatus(OPEN, { ms: 230_000, spedUp: false, compact: false }).text).toBe('Waiting 3 min 50 s')
    expect(stepStatus(OPEN, { ms: 230_000, spedUp: true, compact: false }).text).toBe('Waiting 3 min (sped up)')
    expect(stepStatus(OPEN, { ms: 40_000, spedUp: true, compact: false }).text).toBe('Waiting 40 s (sped up)')
    expect(stepStatus(OPEN, { ms: 230_000, spedUp: true, compact: true }).text).toBe('Waiting 3 min 50 s')
    expect(stepStatus(OPEN, null)).toEqual({ text: 'Waiting', tone: 'wait' })
  })
})

const JIRA = doorKey('jira')

const proposal: Ticket = {
  proposalId: 'p1',
  digest: 'abc',
  proposer: agentId('room_lead'),
  lines: [{ connector: JIRA, operation: 'create_ticket', line: 'Create Jira ticket in MOCK: New LangGraph releases', reference: null }],
  denied: null,
}

describe('the write door', () => {
  it('is named after its connector as soon as one is known, else after the block it was seeded from', () => {
    expect(doorName({ side: 'write', key: JIRA, label: 'Create Jira ticket' })).toBe('Jira')
    expect(doorName({ side: 'write', key: null, label: 'Create Jira ticket' })).toBe('Create Jira ticket')
    expect(doorName({ side: 'read', key: doorKey('github'), label: null })).toBe('GitHub')
    expect(doorName({ side: 'teams', key: 'teams', label: null })).toBe('Teams')
  })

  it('says what goes through it without repeating its own name: the seeded block, the proposal, or nothing', () => {
    expect(writeDoorAction({ side: 'write', key: JIRA, label: 'Create Jira ticket' }, null)).toBe('Create ticket')
    expect(writeDoorAction({ side: 'write', key: JIRA, label: 'Update the JIRA board' }, null)).toBe('Update the board')
    expect(writeDoorAction({ side: 'write', key: null, label: 'Create a ticket' }, null)).toBe('Create a ticket')
    expect(writeDoorAction({ side: 'write', key: JIRA, label: null }, proposal)).toBe('Create a ticket')
    expect(writeDoorAction({ side: 'write', key: JIRA, label: null }, null)).toBeNull()
  })

  it('reads as one line: the action, then the state, with the checker silent while locked', () => {
    const locked = writeDoorStatus('locked', [], false)
    expect(writeDoorLine('Create ticket', locked)).toEqual({ text: 'Create ticket. Locked until an Approver says yes.', tone: 'quiet' })
    expect(writeDoorLine(null, locked)).toEqual(locked)
    expect(writeDoorLine('Create ticket', writeDoorStatus('allowed', ['Bob'], true)).text).toBe('Create ticket. Allowed. Approved by Bob.')
    expect(writeDoorLine('Create ticket', writeDoorStatus('locked', ['Bob'], false)).text).toBe('Create ticket. Approved by Bob. Not written yet.')
    expect(writeDoorLine('Create ticket', writeDoorStatus('blocked', [], false)).text).toBe('Create ticket. Blocked by the safety checker.')
    expect(checkerStatus('locked')).toBeNull()
    expect(checkerStatus('allowed')).toEqual({ text: 'Allowed', tone: 'done' })
    expect(checkerStatus('blocked')).toEqual({ text: 'Blocked', tone: 'fail' })
  })
})

describe('the draft on the table', () => {
  it("splits the proposal's line into the action and the title at the first colon, and keeps a line without one whole", () => {
    expect(splitActionLine('Create Jira ticket in MOCK: New LangGraph releases: 1.2.16, 1.2.15')).toEqual({
      action: 'Create Jira ticket in MOCK',
      title: 'New LangGraph releases: 1.2.16, 1.2.15',
    })
    expect(splitActionLine('Create a ticket')).toEqual({ action: null, title: 'Create a ticket' })
    expect(splitActionLine(': untitled')).toEqual({ action: null, title: ': untitled' })
    expect(splitActionLine('Create a ticket: ')).toEqual({ action: null, title: 'Create a ticket: ' })
  })
})
