import { describe, expect, it } from 'vitest'
import { connectorNamedIn, objectNoun, starterName } from './labels'

describe('connectorNamedIn', () => {
  it('finds the connector a block names as a whole word, in any case', () => {
    expect(connectorNamedIn('Create Jira ticket')).toBe('jira')
    expect(connectorNamedIn('update the GITHUB release notes')).toBe('github')
  })

  it('names nothing for words that hold no connector, or only part of one', () => {
    expect(connectorNamedIn('Send an email')).toBeNull()
    expect(connectorNamedIn('Open Jiramatic')).toBeNull()
  })
})

describe('objectNoun', () => {
  it('reads the thing an operation writes from its last word', () => {
    expect(objectNoun('create_ticket')).toBe('ticket')
    expect(objectNoun('update_confluence_page')).toBe('page')
  })

  it('names nothing for an operation key with no object part', () => {
    expect(objectNoun('publish')).toBe('')
    expect(objectNoun('')).toBe('')
  })
})

describe('starterName', () => {
  it('names the schedule when a schedule started the run', () => {
    expect(starterName('Alice', 'person')).toBe('Alice')
    expect(starterName('Alice', 'schedule')).toBe("Alice's schedule")
    expect(starterName('Alice', undefined), 'a run from before schedules').toBe('Alice')
  })
})
