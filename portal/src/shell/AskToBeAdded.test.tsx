import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { ApiProvider } from '../api/context'
import { SIGNED_IN, type Session } from '../api/session'
import type { Me } from '../api/types'
import { ASK_HEADING } from './AskToBeAdded'

const ORIGIN = 'http://portal.test'

const session: Session = {
  kind: 'oidc',
  cacheScope: () => 'subject-1',
  status: () => SIGNED_IN,
  subscribe: () => () => undefined,
  credentials: () => Promise.resolve({}),
  refusedByPlatform: () => undefined,
  signIn: () => Promise.resolve(),
  signOut: () => Promise.resolve(),
}

function render(me: Me, path = '/workflows'): string {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin={ORIGIN}>
        <MemoryRouter initialEntries={[path]}>
          <App now={() => new Date('2026-10-29T03:00:00Z')} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''

describe('someone signed in but not on the People list', () => {
  const mallory: Me = { id: '0a110e70-0000-4000-8000-000000000006', display: 'Mallory', roles: [], on_list: false }

  it('is asked to find an Operator instead of seeing the page', () => {
    const main = text(mainOf(render(mallory)))
    expect(main).toContain(ASK_HEADING)
    expect(main).toContain('signed in as Mallory')
    expect(main).not.toContain('Workflows')
  })

  it('still sees their name in the header', () => {
    expect(render(mallory)).toContain('Mallory')
  })

  it('is told the same on every path', () => {
    for (const path of ['/', '/agents', '/settings']) {
      expect(text(mainOf(render(mallory, path)))).toContain(ASK_HEADING)
    }
  })
})

describe('someone on the People list', () => {
  it('sees the page they asked for', () => {
    const alice: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'], on_list: true }
    const main = text(mainOf(render(alice)))
    expect(main).not.toContain(ASK_HEADING)
    expect(main).toContain('Workflows')
  })
})
