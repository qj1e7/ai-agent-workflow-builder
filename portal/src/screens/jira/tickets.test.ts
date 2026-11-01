import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { createLatch, type Outcome } from '../../api/latch'
import type { MockJiraTicket } from '../../api/types'
import { doneWords, EMPTY_WORDS, LOAD_WORDS, markDoneProblem, missingWords, newestFirst, showMarkDone, pressMarkDone, splitKeys, ticketHref, ticketPath } from './tickets'

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
    const list = [ticket('OPS-2', '2026-11-01T01:00:00Z'), ticket('OPS-10', '2026-11-03T01:00:00Z'), ticket('OPS-9', '2026-11-03T01:00:00Z')]
    expect(newestFirst(list).map((t) => t.key)).toEqual(['OPS-10', 'OPS-9', 'OPS-2'])
  })

  it('does not change the list it was given', () => {
    const list = [ticket('OPS-1', '2026-11-01T01:00:00Z'), ticket('OPS-2', '2026-11-02T01:00:00Z')]
    newestFirst(list)
    expect(list.map((t) => t.key)).toEqual(['OPS-1', 'OPS-2'])
  })

  it('offers Mark done only to an Operator, and only on a ticket that is not Done', () => {
    expect(showMarkDone(ticket('OPS-1', '2026-11-01T01:00:00Z'), true)).toBe(true)
    expect(showMarkDone(ticket('OPS-1', '2026-11-01T01:00:00Z'), false)).toBe(false)
    expect(showMarkDone(ticket('OPS-1', '2026-11-01T01:00:00Z', 'Done'), true)).toBe(false)
  })
})

describe('ticket keys in a line of words', () => {
  it('links exactly the keys it is given, in any project, and leaves the rest as it was', () => {
    expect(splitKeys('Created OPS-142 and OPS-7 in Jira.', ['OPS-142', 'OPS-7'])).toEqual([
      { text: 'Created ', key: false },
      { text: 'OPS-142', key: true },
      { text: ' and ', key: false },
      { text: 'OPS-7', key: true },
      { text: ' in Jira.', key: false },
    ])
  })

  it('returns one plain piece when it is given no key, and none for empty words', () => {
    expect(splitKeys('Done. Nothing was written.', [])).toEqual([{ text: 'Done. Nothing was written.', key: false }])
    expect(splitKeys('Created OPS-1 in Jira.', [])).toEqual([{ text: 'Created OPS-1 in Jira.', key: false }])
    expect(splitKeys('', ['OPS-1'])).toEqual([])
  })

  it('does not take other key-like words, such as UTF-8 or CVE-2024-1234, or a key it was not given', () => {
    expect(splitKeys('UTF-8, CVE-2024-1234 and OPS-9', ['OPS-1'])).toEqual([{ text: 'UTF-8, CVE-2024-1234 and OPS-9', key: false }])
  })

  it('does not take a given key from the middle of a longer one', () => {
    expect(splitKeys('OPS-12 and XOPS-1', ['OPS-1'])).toEqual([{ text: 'OPS-12 and XOPS-1', key: false }])
  })

  it('takes a key that holds regex characters literally', () => {
    expect(splitKeys('See A.B-1', ['A.B-1'])).toEqual([
      { text: 'See ', key: false },
      { text: 'A.B-1', key: true },
    ])
    expect(splitKeys('See AxB-1', ['A.B-1'])).toEqual([{ text: 'See AxB-1', key: false }])
  })

  it('links to the page with that ticket open, with the key made safe for an address', () => {
    expect(ticketPath('OPS-142')).toBe('/jira/OPS-142')
    expect(ticketPath('A B/1')).toBe('/jira/A%20B%2F1')
  })

  it('sends a link to the practice page when no Jira address is configured', () => {
    expect(ticketHref('OPS-142', null)).toEqual({ href: '/jira/OPS-142', external: false })
  })

  it('sends a link to the configured Jira, as an outside link, with the key put in and made safe', () => {
    expect(ticketHref('OPS-142', 'https://jira.example.test/browse/{key}')).toEqual({ href: 'https://jira.example.test/browse/OPS-142', external: true })
    expect(ticketHref('A B/1', 'https://jira.example.test/browse/{key}').href).toBe('https://jira.example.test/browse/A%20B%2F1')
  })
})

describe('the words on the practice Jira page', () => {
  it('says what an empty list means and where the tickets come from', () => {
    expect(EMPTY_WORDS).toBe('No tickets yet. When a run creates one after a yes, it shows here.')
  })

  it('says the list could not be loaded', () => {
    expect(LOAD_WORDS).toBe('The tickets could not be loaded.')
  })

  it('says only that the ticket is Done, because the watchlist moves a version only for tickets it wrote', () => {
    expect(doneWords('OPS-3')).toBe('OPS-3 is Done.')
  })

  it('says when a linked ticket is not in the list', () => {
    expect(missingWords('OPS-99')).toBe('OPS-99 is not in the practice Jira.')
  })

  it('explains a 404 and a 403 for Mark done in plain words', () => {
    expect(markDoneProblem(new ApiError(404, { detail: 'No such ticket' }), 'OPS-3', words)).toBe(
      'OPS-3 is not in the practice Jira any more. The list is up to date now.',
    )
    expect(markDoneProblem(new ApiError(403, { detail: 'Operators only' }), 'OPS-3', words)).toBe(
      'Only an Operator can mark a ticket Done. Ask an Operator to do it.',
    )
  })

  it('uses the shared words for any other trouble', () => {
    expect(markDoneProblem(new Error('The platform had a problem.'), 'OPS-3', words)).toBe('OPS-3 is not Done yet. The platform had a problem.')
  })
})

describe('pressing Mark done', () => {
  function setup(answer: (outcome: Outcome) => void) {
    const calls: string[] = []
    const ui = {
      start: () => calls.push('start'),
      armFocus: () => calls.push('armFocus'),
      done: (said: string) => calls.push(`done:${said}`),
      fail: (said: string) => calls.push(`fail:${said}`),
      settled: () => calls.push('settled'),
    }
    const latch = createLatch()
    const sent: string[] = []
    const mutate = (key: string, outcome: Outcome) => {
      sent.push(key)
      answer(outcome)
    }
    return { calls, ui, latch, mutate, sent }
  }

  it('says the ticket is Done and asks for focus to move once the row reads Done', () => {
    const { calls, ui, latch, mutate } = setup((outcome) => {
      outcome.onSuccess?.(undefined)
      outcome.onSettled?.()
    })
    pressMarkDone(latch, mutate, 'OPS-3', ui, words)
    expect(calls).toEqual(['start', 'armFocus', 'done:OPS-3 is Done.', 'settled'])
  })

  it('says why in plain words for a 403 and a 404, and does not move focus', () => {
    for (const [status, said] of [
      [403, 'Only an Operator can mark a ticket Done. Ask an Operator to do it.'],
      [404, 'OPS-3 is not in the practice Jira any more. The list is up to date now.'],
    ] as const) {
      const { calls, ui, latch, mutate } = setup((outcome) => {
        outcome.onError?.(new ApiError(status, {}))
        outcome.onSettled?.()
      })
      pressMarkDone(latch, mutate, 'OPS-3', ui, words)
      expect(calls).toEqual(['start', `fail:${said}`, 'settled'])
    }
  })

  it('sends one request for two quick presses', () => {
    const { ui, latch, mutate, sent } = setup(() => undefined)
    pressMarkDone(latch, mutate, 'OPS-3', ui, words)
    pressMarkDone(latch, mutate, 'OPS-3', ui, words)
    expect(sent).toEqual(['OPS-3'])
  })
})
