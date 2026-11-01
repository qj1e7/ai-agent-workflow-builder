import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import type { MockJiraTicket } from '../../api/types'
import { doneWords, EMPTY_WORDS, LOAD_WORDS, markDoneProblem, missingWords, newestFirst, showMarkDone, splitKeys, ticketHref, ticketPath } from './tickets'

function ticket(key: string, created_at: string, status: MockJiraTicket['status'] = 'To Do'): MockJiraTicket {
  return {
    key,
    project: 'MOCK',
    title: `Upgrade for ${key}`,
    body: '',
    created_at,
    run_id: 'run_1',
    proposal_id: 'prp_1',
    status,
    done_at: null,
  }
}

const words = (error: unknown) => (error instanceof Error ? error.message : 'odd')

describe('the practice Jira list', () => {
  it('puts the newest ticket first, and the higher number first when two share a time', () => {
    const list = [ticket('MOCK-2', '2026-11-01T01:00:00Z'), ticket('MOCK-10', '2026-11-03T01:00:00Z'), ticket('MOCK-9', '2026-11-03T01:00:00Z')]
    expect(newestFirst(list).map((t) => t.key)).toEqual(['MOCK-10', 'MOCK-9', 'MOCK-2'])
  })

  it('does not change the list it was given', () => {
    const list = [ticket('MOCK-1', '2026-11-01T01:00:00Z'), ticket('MOCK-2', '2026-11-02T01:00:00Z')]
    newestFirst(list)
    expect(list.map((t) => t.key)).toEqual(['MOCK-1', 'MOCK-2'])
  })

  it('offers Mark done only to an Operator, and only on a ticket that is not Done', () => {
    expect(showMarkDone(ticket('MOCK-1', '2026-11-01T01:00:00Z'), true)).toBe(true)
    expect(showMarkDone(ticket('MOCK-1', '2026-11-01T01:00:00Z'), false)).toBe(false)
    expect(showMarkDone(ticket('MOCK-1', '2026-11-01T01:00:00Z', 'Done'), true)).toBe(false)
  })
})

describe('ticket keys in a line of words', () => {
  it('finds each MOCK key and leaves the rest as it was', () => {
    expect(splitKeys('Created MOCK-142 and MOCK-7 in Jira.')).toEqual([
      { text: 'Created ', key: false },
      { text: 'MOCK-142', key: true },
      { text: ' and ', key: false },
      { text: 'MOCK-7', key: true },
      { text: ' in Jira.', key: false },
    ])
  })

  it('returns one plain piece when there is no key, and none for empty words', () => {
    expect(splitKeys('Done. Nothing was written.')).toEqual([{ text: 'Done. Nothing was written.', key: false }])
    expect(splitKeys('')).toEqual([])
  })

  it('does not take a key from the middle of another word', () => {
    expect(splitKeys('NOMOCK-1 and MOCK-12x')).toEqual([{ text: 'NOMOCK-1 and MOCK-12x', key: false }])
  })

  it('links to the page with that ticket open', () => {
    expect(ticketPath('MOCK-142')).toBe('/jira/MOCK-142')
  })

  it('sends a link to the practice page when no Jira address is configured', () => {
    expect(ticketHref('MOCK-142', null)).toEqual({
      href: '/jira/MOCK-142',
      external: false,
    })
  })

  it('sends a link to the configured Jira, as an outside link, with the key put in', () => {
    expect(ticketHref('MOCK-142', 'https://jira.example.test/browse/{key}')).toEqual({
      href: 'https://jira.example.test/browse/MOCK-142',
      external: true,
    })
  })
})

describe('the words on the practice Jira page', () => {
  it('says what an empty list means and where the tickets come from', () => {
    expect(EMPTY_WORDS).toBe('No tickets yet. When a run creates one after a yes, it shows here.')
  })

  it('says the list could not be loaded', () => {
    expect(LOAD_WORDS).toBe('The tickets could not be loaded.')
  })

  it('says the ticket is Done and that the watchlist follows', () => {
    expect(doneWords('MOCK-3')).toBe('MOCK-3 is Done. The Software watchlist has its new version.')
  })

  it('says when a linked ticket is not in the list', () => {
    expect(missingWords('MOCK-99')).toBe('MOCK-99 is not in the practice Jira.')
  })

  it('explains a 404 and a 403 for Mark done in plain words', () => {
    expect(markDoneProblem(new ApiError(404, { detail: 'No such ticket' }), 'MOCK-3', words)).toBe(
      'MOCK-3 is not in the practice Jira any more. The list is up to date now.',
    )
    expect(markDoneProblem(new ApiError(403, { detail: 'Operators only' }), 'MOCK-3', words)).toBe(
      'Only an Operator can mark a ticket Done. Ask an Operator to do it.',
    )
  })

  it('uses the shared words for any other trouble', () => {
    expect(markDoneProblem(new Error('The platform had a problem.'), 'MOCK-3', words)).toBe('MOCK-3 is not Done yet. The platform had a problem.')
  })
})
