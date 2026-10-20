import { describe, expect, it } from 'vitest'
import { connectorNamedIn } from './labels'

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
