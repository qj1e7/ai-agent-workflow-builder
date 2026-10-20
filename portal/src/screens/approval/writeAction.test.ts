import { describe, expect, it } from 'vitest'
import type { WriteActionView } from '../../api/types'
import { describeAction, systemsWritten } from './writeAction'

const ticket: WriteActionView = {
  connector: 'jira',
  operation: 'create_ticket',
  target: { project: 'MOCK' },
  fields: { title: 'New LangGraph releases: 1.2.16, 1.2.15', body: 'Releases newer than 1.2.14:\n- 1.2.16' },
}

describe('describeAction', () => {
  it('names the system, the action and the project in words', () => {
    expect(describeAction(ticket).rows).toEqual([
      { label: 'System', value: 'Jira' },
      { label: 'Action', value: 'Create a ticket' },
      { label: 'Project', value: 'MOCK' },
    ])
  })

  it('splits out the title and keeps the body as written', () => {
    const { title, body } = describeAction(ticket)
    expect(title).toBe('New LangGraph releases: 1.2.16, 1.2.15')
    expect(body).toBe('Releases newer than 1.2.14:\n- 1.2.16')
  })

  it('lists every other field so nothing that gets written is hidden', () => {
    const labelled = describeAction({ ...ticket, fields: { ...ticket.fields, priority: 'High', labels: ['release', 'check'] } })
    expect(labelled.rows.slice(3)).toEqual([
      { label: 'Priority', value: 'High' },
      { label: 'Labels', value: '["release","check"]' },
    ])
  })

  it('copes with a request that has no title or body', () => {
    expect(describeAction({ ...ticket, fields: {} })).toMatchObject({ title: null, body: null })
  })
})

describe('systemsWritten', () => {
  it('names one system once and joins several in plain words', () => {
    expect(systemsWritten([ticket, ticket])).toBe('Jira')
    expect(systemsWritten([ticket, { ...ticket, connector: 'confluence' }])).toBe('Jira and Confluence')
  })
})
