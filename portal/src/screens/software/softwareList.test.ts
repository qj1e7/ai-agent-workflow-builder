import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { describe, expect, it } from 'vitest'
import type { WatchlistView } from '../../api/types'
import { NOT_SET, oursFrom, softwareList, upToDateWords } from './softwareList'

const view = statuses as WatchlistView

describe('softwareList', () => {
  it('keeps the platform order for rows that need a person and folds the up to date ones', () => {
    const list = softwareList(view)
    expect(list.attention.map((row) => [row.name, row.status])).toEqual([
      ['FastAPI', 'cant_check'],
      ['LangGraph', 'behind'],
      ['Redis', 'awaiting_approval'],
      ['PostgreSQL', 'ticket_open'],
      ['Terraform', 'not_checked'],
    ])
    expect(list.upToDate.map((row) => row.name)).toEqual(['n8n'])
    expect(upToDateWords(list.upToDate.length)).toBe('1 up to date')
  })

  it('gives each row the action that resolves it', () => {
    const byName = new Map(softwareList(view).attention.map((row) => [row.name, row]))
    expect(byName.get('Redis')?.next).toEqual({ is: 'approval', to: '/approvals/apr_01JBB' })
    expect(byName.get('PostgreSQL')?.next).toEqual({ is: 'ticket', key: 'MOCK-143' })
    expect(byName.get('LangGraph')?.next).toBeNull()
    expect(byName.get('FastAPI')?.problem).toBe('GitHub answered 404 Not Found.')
    expect(byName.get('LangGraph')?.problem, 'only a row that could not be checked carries a problem').toBeNull()
  })

  it('labels every status through one table', () => {
    const labels = Object.fromEntries(softwareList(view).attention.map((row) => [row.status, [row.label, row.tone]]))
    expect(labels).toEqual({
      cant_check: ["Can't check", 'failed'],
      behind: ['Behind', 'waiting'],
      awaiting_approval: ['Waiting for approval', 'waiting'],
      ticket_open: ['Ticket open', 'working'],
      not_checked: ['Not checked yet', 'neutral'],
    })
  })

  it('reads a missing watchlist as an empty one', () => {
    expect(softwareList(null)).toEqual({ attention: [], upToDate: [] })
  })
})

describe('oursFrom', () => {
  it('says where our version came from in a few words', () => {
    expect(oursFrom({ kind: 'given', at: '2026-11-02T10:00:00Z', ticket: null })).toBe('Given when added')
    expect(oursFrom({ kind: 'first_check', at: '2026-11-09T01:00:00Z', ticket: null })).toBe(
      'Newest at the first check',
    )
    expect(oursFrom({ kind: 'ticket_done', at: '2026-10-24T03:00:00Z', ticket: 'MOCK-7' })).toBe(
      'From MOCK-7, Done 24 Oct',
    )
    expect(oursFrom(null)).toBe(NOT_SET)
  })

  it('says a version is still to come before the first check', () => {
    const terraform = softwareList(view).attention.find((row) => row.name === 'Terraform')
    expect(terraform?.ours).toBeNull()
    expect(terraform?.oursFrom).toBe(NOT_SET)
  })
})
