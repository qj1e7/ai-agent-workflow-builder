import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, QuestionReply, WatchlistView } from '../../api/types'
import { Answer, type Page } from './AnswerCards'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const LIST = statuses as WatchlistView

function draw(me: Me, names: string[], view: WatchlistView | null = LIST): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['watchlist', session.cacheScope()], view)
  const reply: QuestionReply = { ...(question as QuestionReply), about_software: names }
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Answer reply={reply} typed="Is there a newer version of it?" page={PAGE} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))

describe('the Software-page actions under an answer about watched software', () => {
  it('gives an Operator Open, Stop watching last for the software, and the check of the whole watchlist', () => {
    const html = draw(ALICE, ['fastapi'])
    expect(buttons(html)).toEqual(['Software', 'Open FastAPI on the Software page', 'Stop watching FastAPI', 'Check all software now'])
    expect(html).toContain(`href="/software/${LIST.software[0]?.id}"`)
  })

  it('names one software once, as the card’s title, and several by row under “On your watchlist”', () => {
    const one = draw(ALICE, ['FastAPI'])
    expect(one).toMatch(/<h3 id="[^"]*">FastAPI<\/h3>/)
    expect(one).not.toContain('<b>FastAPI</b>')
    const two = draw(ALICE, ['FastAPI', 'Redis'])
    expect(two).toMatch(/<h3 id="[^"]*">On your watchlist<\/h3>/)
    expect(two).toContain('<b>FastAPI</b>')
    expect(two).toContain('<b>Redis</b>')
  })

  it('asks before it stops watching, so the first press removes nothing', () => {
    const html = draw(ALICE, ['FastAPI'])
    expect(text(html)).not.toContain('Yes, stop watching')
    expect(text(html)).not.toContain('Undo')
  })

  it('gives an Approver nothing, as the Software page does', () => {
    expect(buttons(draw(BOB, ['FastAPI']))).toEqual(['Software'])
  })

  it('gives nothing for a name the watchlist does not hold, or before the watchlist has loaded', () => {
    expect(buttons(draw(ALICE, ['Kubernetes']))).toEqual(['Software'])
    expect(buttons(draw(ALICE, ['FastAPI'], null))).toEqual(['Software'])
  })

  it('leaves out the check while the watchlist is paused', () => {
    expect(buttons(draw(ALICE, ['FastAPI'], { ...LIST, state: 'paused' }))).not.toContain('Check all software now')
  })

  it('shows no action under an answer that is about no software in particular', () => {
    expect(buttons(draw(ALICE, []))).toEqual(['Software'])
  })
})
