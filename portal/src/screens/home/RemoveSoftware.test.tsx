import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import removal from '../../../../contracts/fixtures/planner/answer.remove_software.json'
import notHeld from '../../../../contracts/fixtures/planner/answer.remove_software.none.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PartView, RemoveSoftwareReply } from '../../api/types'
import { Answer, type Page } from './AnswerCards'
import { removeSay, sayOf, wordsOnly } from './answers'
import { leftoverParts } from './parts'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const ONE = removal as RemoveSoftwareReply
const NONE = notHeld as RemoveSoftwareReply
const SEVERAL: RemoveSoftwareReply = {
  ...ONE,
  software: 'nodejs',
  matches: [
    { software_id: 'sw_01JD4', name: 'node js' },
    { software_id: 'sw_01JD5', name: 'Node.js' },
  ],
}

function draw(me: Me, reply: RemoveSoftwareReply): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['people', session.cacheScope()], [{ id: 'alice', display: 'Alice', operator: true }])
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Answer reply={reply} typed="remove Node.js from the watchlist" page={PAGE} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

describe('software to take off the Watchlist', () => {
  it('asks about the one match by the name the watchlist holds, and offers the Software page’s Remove', () => {
    expect(sayOf(ONE)).toBe('Remove node js from the Watchlist? It won’t be checked any more.')
    expect(wordsOnly(ONE, 'operator')).toBe(false)
    const html = draw(ALICE, ONE)
    expect(html).toMatch(/<h3 id="[^"]*">node js<\/h3>/)
    expect(buttons(html)).toEqual(['Remove from watchlist node js'])
    expect(text(html)).not.toContain('Undo')
  })

  it('offers each of several matches, by name, to choose', () => {
    expect(sayOf(SEVERAL)).toBe('More than one software on your Watchlist could be nodejs. Which one should I remove?')
    const html = draw(ALICE, SEVERAL)
    expect(html).toMatch(/<h3 id="[^"]*">On your Watchlist<\/h3>/)
    expect(buttons(html)).toEqual(['Remove from watchlist node js', 'Remove from watchlist Node.js'])
  })

  it('says a name the watchlist doesn’t hold isn’t there, names what it holds, and offers nothing to remove', () => {
    expect(sayOf(NONE)).toBe('Kubernetes isn’t on your Watchlist. It holds FastAPI, LangGraph, node js and React.')
    expect(wordsOnly(NONE, 'operator')).toBe(true)
    expect(buttons(draw(ALICE, NONE))).toEqual([])
  })

  it('counts the names past eight, and says when the watchlist is empty', () => {
    const many = Array.from({ length: 11 }, (_, n) => `Tool ${String(n + 1)}`)
    expect(removeSay({ ...NONE, watched: many })).toBe('Kubernetes isn’t on your Watchlist. It holds Tool 1, Tool 2, Tool 3, Tool 4, Tool 5, Tool 6, Tool 7, Tool 8 and 3 more.')
    expect(removeSay({ ...NONE, watched: [] })).toBe('Kubernetes isn’t on your Watchlist. Your Watchlist is empty.')
  })

  it('gives someone who isn’t an Operator who to ask, and no button', () => {
    const html = draw(BOB, ONE)
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain('Only Operators change the watchlist. Ask Alice.')
  })

  it('draws a part it didn’t do above the card, so none is dropped', () => {
    const add: PartView = { text: 'add Redis', mark: 'cant', reason: 'ask_on_its_own', note: null, choices: [] }
    expect(leftoverParts({ ...ONE, parts: [...ONE.parts, add] })).toEqual([add])
  })
})
