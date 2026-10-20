import { describe, expect, it } from 'vitest'
import { agentId, doorKey, type Ticket } from '../run'
import { doorName, writeDoorAction } from './words'

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

  it('says what goes through it: the seeded block, the proposal, or nothing', () => {
    expect(writeDoorAction({ side: 'write', key: JIRA, label: 'Create Jira ticket' }, null)).toBe('Create Jira ticket')
    expect(writeDoorAction({ side: 'write', key: JIRA, label: null }, proposal)).toBe('Create a ticket')
    expect(writeDoorAction({ side: 'write', key: JIRA, label: null }, null)).toBeNull()
  })
})
