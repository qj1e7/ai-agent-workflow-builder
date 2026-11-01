import stubs from '@contracts/fixtures/stubs/mock-jira-tickets.json'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, MockJiraTicket } from '../../api/types'
import { JiraRoute } from './JiraPage'

const ALICE: Me = {
  id: 'alice',
  display: 'Alice',
  roles: ['operator', 'approver'],
}
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

const FIRST = { ...(stubs.tickets as MockJiraTicket[])[0], key: 'OPS-142', project: 'OPS' } as MockJiraTicket
const OLDER: MockJiraTicket = {
  ...FIRST,
  key: 'OPS-141',
  title: 'Upgrade FastAPI from 0.115.0 to 0.115.2',
  body: 'FastAPI has 1 new release.',
  created_at: '2026-11-02T02:00:00Z',
  status: 'Done',
  done_at: '2026-11-02T03:00:00Z',
  run_id: 'run_00A',
}

interface Setup {
  readonly tickets?: readonly MockJiraTicket[] | 'error'
  readonly me?: Me
  readonly path?: string
}

function render({ tickets = [FIRST, OLDER], me = ALICE, path = '/jira' }: Setup = {}): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retryOnMount: false } },
  })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  const key = ['jira-tickets', session.cacheScope()]
  if (tickets === 'error')
    queryClient
      .getQueryCache()
      .build(queryClient, { queryKey: key })
      .setState({
        status: 'error',
        error: new ApiError(500, {}),
        fetchStatus: 'idle',
      })
  else queryClient.setQueryData(key, tickets)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/jira/:key?" element={<JiraRoute />} />
          </Routes>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html
    .replace(/<[^>]*>/g, ' ')
    .replaceAll('&#x27;', "'")
    .replace(/\s+/g, ' ')
    .trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))
const rowOf = (html: string, key: string) =>
  [...html.matchAll(/<li\b[^>]*data-ticket="([^"]*)"[^>]*>([\s\S]*?)<\/li>/g)].find((match) => match[1] === key)?.[2] ?? ''

describe('the practice Jira page', () => {
  it('lists every ticket newest first with key, title, status, when it was made and a link to its run', () => {
    const html = render()
    const keys = [...html.matchAll(/data-ticket="([^"]*)"/g)].map((match) => match[1])
    expect(keys).toEqual(['OPS-142', 'OPS-141'])
    const first = text(rowOf(html, 'OPS-142'))
    expect(first).toContain('Upgrade LangGraph from 1.2.14 to 1.2.16')
    expect(first).toContain('To Do')
    expect(first).toContain('Created Tue 3 Nov, 10:20')
    expect(rowOf(html, 'OPS-142')).toContain('href="/runs/run_01JB8"')
    expect(rowOf(html, 'OPS-141')).toContain('href="/runs/run_00A"')
    expect(text(rowOf(html, 'OPS-141'))).toContain('Done')
  })

  it('shows Mark done on tickets that are not Done for an Operator', () => {
    const html = render()
    expect(buttons(rowOf(html, 'OPS-142'))).toContain('Mark done OPS-142')
    expect(buttons(rowOf(html, 'OPS-141')).join(' ')).not.toContain('Mark done')
  })

  it('shows no Mark done to an Approver who is not an Operator', () => {
    expect(buttons(render({ me: BOB })).join(' ')).not.toContain('Mark done')
  })

  it('keeps the description out of sight until a ticket is opened', () => {
    const html = render()
    expect(html).not.toContain('Proposed by the AI workflow builder')
    expect(rowOf(html, 'OPS-142')).toContain('aria-expanded="false"')
  })

  it('opens the ticket a link names, with its description, and says the toggle is expanded', () => {
    const html = render({ path: '/jira/OPS-142' })
    expect(text(rowOf(html, 'OPS-142'))).toContain('Proposed by the AI workflow builder')
    expect(rowOf(html, 'OPS-142')).toContain('aria-expanded="true"')
    expect(rowOf(html, 'OPS-141')).toContain('aria-expanded="false"')
  })

  it('says when a linked ticket is not in the list, and still lists the others', () => {
    const html = render({ path: '/jira/OPS-99' })
    expect(text(html)).toContain('OPS-99 is not in the practice Jira.')
    expect(html).toContain('data-ticket="OPS-142"')
  })

  it('has an empty state', () => {
    const html = render({ tickets: [] })
    expect(text(html)).toContain('No tickets yet. When a run creates one after a yes, it shows here.')
    expect(html).not.toContain('data-ticket')
  })

  it('has an error state with Try again', () => {
    const html = render({ tickets: 'error' })
    expect(text(html)).toContain('The tickets could not be loaded.')
    expect(buttons(html)).toContain('Try again')
  })

  it('keeps an empty status line on the page so a screen reader hears each message', () => {
    expect(render()).toMatch(/<p[^>]*role="status"[^>]*><\/p>/)
  })

  it('has a level 2 heading for each ticket, under the page’s level 1 heading', () => {
    const html = render()
    expect([...html.matchAll(/<h2\b/g)]).toHaveLength(2)
  })
})
