import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import type { Pager } from '../../api/homeQueries'
import { createDevSession } from '../../api/session'
import { ApprovalCards } from './ApprovalCards'
import { CardMemoryContext, newCardMemory, type RequestRef } from './cardMemory'

const IDLE: Pager = { busy: false, failed: false, showMore: () => undefined }
const ref = (runId: string): RequestRef => ({ approvalId: null, runId })
const WAITING = ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'].map(ref)

function draw(kept: readonly RequestRef[], items: readonly RequestRef[], total: number, more?: Pager): string {
  const session = createDevSession({ getItem: () => 'alice', setItem: () => undefined })
  const memory = newCardMemory()
  if (kept.length > 0) memory.approvals.keep(kept)
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>
            <ApprovalCards items={items} total={total} nameOf={(id) => id} {...(more ? { more } : {})} />
          </CardMemoryContext.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

describe('her own requests that wait for someone else’s yes', () => {
  it('keeps a decided card, but counts only what still waits, so Show more reaches the last one', () => {
    const html = draw([ref('A'), ref('B'), ref('C')], WAITING, 9, IDLE)
    expect([...html.matchAll(/data-run-card="([^"]+)"/g)].map((m) => m[1])).toEqual(['A', 'B', 'C'])
    expect(html).toMatch(/role="status"[^>]*>Showing 2 of 9\.<\/p>/)
    expect(html).toContain('>Show more</button>')
  })

  it('still offers Show more when the one decided card would have hidden the last request', () => {
    const html = draw([ref('A'), ref('B'), ref('C')], [ref('B'), ref('C'), ref('D')], 3, IDLE)
    expect(html).toMatch(/Showing 2 of 3\./)
    expect(html).toContain('>Show more</button>')
  })
})

describe('requests waiting for her own yes', () => {
  it('shows three, then N more, which leads to Needs you, where every one is listed', () => {
    const html = draw([], WAITING, 9)
    expect([...html.matchAll(/data-run-card="([^"]+)"/g)].map((m) => m[1])).toEqual(['B', 'C', 'D'])
    expect(html).toMatch(/href="\/workflows"[^>]*>6 more</)
    expect(html).not.toContain('Show more')
  })
})
