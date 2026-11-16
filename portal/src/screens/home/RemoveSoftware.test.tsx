import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import removal from '../../../../contracts/fixtures/planner/answer.remove_software.json'
import notHeld from '../../../../contracts/fixtures/planner/answer.remove_software.none.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PartView, RemoveSoftwareReply, WatchlistView } from '../../api/types'
import { Answer, type Page } from './AnswerCards'
import { removeSay, sayOf, wordsOnly } from './answers'
import { CardMemoryContext, newCardMemory, NO_MEMORY, type CardMemory } from './cardMemory'
import { leftoverParts } from './parts'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
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

const LIST = statuses as WatchlistView
const [FIRST] = LIST.software
const TWO_NODES: WatchlistView = {
  ...LIST,
  software: SEVERAL.matches.map((match, n) => ({ ...LIST.software[0]!, id: match.software_id, name: match.name, source: { ...FIRST!.source, ref: n === 0 ? 'nodejs/node' : 'nodejs/nodejs.org' } })),
}

function draw(me: Me, reply: RemoveSoftwareReply, memory: CardMemory = NO_MEMORY, view: WatchlistView = LIST): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['watchlist', session.cacheScope()], view)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>
            <Answer reply={reply} typed="remove Node.js from the watchlist" page={PAGE} />
          </CardMemoryContext.Provider>
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

  it('offers each of several matches, by name and source, to choose', () => {
    expect(sayOf(SEVERAL)).toBe('More than one software on your Watchlist could be nodejs. Which one should I remove?')
    const html = draw(ALICE, SEVERAL, NO_MEMORY, TWO_NODES)
    expect(html).toMatch(/<h3 id="[^"]*">On your Watchlist<\/h3>/)
    expect(buttons(html)).toEqual(['Remove from watchlist node js', 'Remove from watchlist Node.js'])
    expect(text(html)).toContain('node js nodejs/node')
    expect(text(html)).toContain('Node.js nodejs/nodejs.org')
  })

  it('keeps a removal and its Undo when Home comes back', () => {
    const memory = newCardMemory()
    const row = { id: ONE.matches[0]!.software_id, name: 'node js' }
    memory.removals.keep({ [row.id]: { kind: 'removed', row } })
    const html = draw(ALICE, ONE, memory)
    expect(text(html)).toContain('Removed from the watchlist.')
    expect(buttons(html)).toEqual(['Undo removing node js'])
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

  it('draws a part it didn’t do above the card, so none is dropped', () => {
    const add: PartView = { text: 'add Redis', mark: 'cant', reason: 'ask_on_its_own', note: null, choices: [] }
    expect(leftoverParts({ ...ONE, parts: [...ONE.parts, add] })).toEqual([add])
  })
})
