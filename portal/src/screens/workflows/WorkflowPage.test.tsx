import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import beforeCheck from '../../../../contracts/fixtures/watchlist/before-check.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, RunView, UseCaseView } from '../../api/types'
import { WHO_APPROVES } from './WorkflowPage'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

const AGENTS = agentUseCase as UseCaseView
const WATCHLIST = watchlistUseCase as UseCaseView
const NOW = new Date('2026-11-04T07:00:00Z')

interface Setup {
  readonly me?: Me
  readonly useCase?: UseCaseView | Error
  readonly runs?: RunView[]
  readonly id?: string
}

function render({ me = ALICE, useCase = AGENTS, runs = [], id }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const useCaseId = id ?? (useCase instanceof Error ? 'uc_gone' : useCase.use_case_id)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['runs', scope], runs)
  queryClient.setQueryData(['watchlist', scope], beforeCheck)
  const key = ['use-case', scope, useCaseId]
  if (useCase instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: useCase, fetchStatus: 'idle' })
  else queryClient.setQueryData(key, useCase)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[`/workflows/${useCaseId}`]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const buttons = (html: string) => [...mainOf(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const factOf = (html: string, term: string) => text(new RegExp(`<dt>${term}</dt><dd>([\\s\\S]*?)</dd>`).exec(html)?.[1] ?? '')

describe('a workflow page', () => {
  it('shows its name, what it does, and whether it is on', () => {
    const html = render()
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe('LangGraph release check')
    expect(text(mainOf(html))).toContain('Check langchain-ai/langgraph for a new release and raise a ticket in MOCK.')
    expect(mainOf(html)).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
  })

  it('says when it runs, when it runs next, and who may approve', () => {
    const html = render()
    expect(factOf(html, 'When')).toBe('No schedule An Operator starts it with Run now.')
    expect(factOf(html, 'Next run')).toBe('Not scheduled')
    expect(factOf(html, 'Who approves')).toBe(`${WHO_APPROVES} Owned by Alice.`)
    expect(WHO_APPROVES).toBe('Any Approver except the people who start or own it')
  })

  it('names its agents, each opening its card', () => {
    const agents = new RegExp('<dt>Agents</dt><dd>([\\s\\S]*?)</dd>').exec(render())?.[1] ?? ''
    expect([...agents.matchAll(/<a[^>]*href="([^"]+)"/g)].map((m) => m[1])).toEqual(['/agents/planner', '/agents/crd_version_checker'])
    expect(text(agents)).toBe('Planner Version checker')
  })

  it('lists its steps, marking the one that changes data', () => {
    const said = text(mainOf(render()))
    expect(said).toContain('What it does')
    expect(said).toContain('Version checker Checks a public GitHub repository for a new release and proposes a Jira ticket for it. Reads only')
    expect(said).toContain('Create Jira tickets Create a Jira ticket, written only after approval. Changes data, waits for a yes')
  })

  it('gives an Operator Run now, Pause and Delete', () => {
    expect(buttons(render())).toEqual(expect.arrayContaining(['Run now', 'Pause', 'Delete']))
  })

  it('gives an Approver who may approve and the recent runs, but no manage buttons', () => {
    const html = render({ me: BOB, runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(factOf(html, 'Who approves')).toContain(WHO_APPROVES)
    expect(text(mainOf(html))).toContain('Recent runs')
    expect(mainOf(html)).toContain('href="/runs/run_01JB8"')
    expect(buttons(html).filter((label) => /Run now|Pause|Resume|Delete/.test(label))).toEqual([])
  })

  it('while paused, offers Resume instead of Pause and Run now, and its next run reads Paused', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused' } })
    expect(buttons(html)).toContain('Resume')
    expect(buttons(html)).not.toContain('Pause')
    expect(buttons(html)).not.toContain('Run now')
    expect(factOf(html, 'Next run')).toBe('Paused')
    expect(mainOf(html)).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
  })

  it('shows a stopped latest run, linking to it, and lets an Operator see why', () => {
    const html = render({ runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }, { ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(mainOf(html)).toMatch(/data-tone="bad"[^>]*>.*Stopped<\/span>/)
    const first = /<li[^>]*data-run-id="([^"]+)"[^>]*data-state="([^"]+)"/.exec(html)
    expect([first?.[1], first?.[2]]).toEqual(['run_01JB9', 'failed'])
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>See why it stopped<\/a>/)
  })

  it('goes back to the list', () => {
    expect(mainOf(render())).toMatch(/<a[^>]*href="\/workflows"[^>]*>[\s\S]*Workflows<\/a>/)
  })

  it('keeps Workflows marked in the menu', () => {
    const current = [...render().matchAll(/<a\b[^>]*aria-current="page"[^>]*>/g)].map((m) => /href="([^"]*)"/.exec(m[0])?.[1])
    expect(new Set(current)).toEqual(new Set(['/workflows']))
  })
})

describe('the Software watchlist as a workflow', () => {
  it('says its schedule, in Singapore time, and who set it', () => {
    expect(factOf(render({ useCase: WATCHLIST }), 'When')).toBe('Every Monday at 9:00 Singapore time, set by Alice.')
  })

  it('can be paused and run, but not deleted, and points to its software', () => {
    const html = render({ useCase: WATCHLIST })
    expect(buttons(html)).toEqual(expect.arrayContaining(['Run now', 'Pause']))
    expect(buttons(html)).not.toContain('Delete')
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/software"[^>]*>See the software it checks<\/a>/)
  })
})

describe('a workflow that is not there', () => {
  it('says so and offers the list', () => {
    const html = render({ useCase: new ApiError(404, { detail: 'No such use case' }) })
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe('Workflow not found')
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/workflows"[^>]*>Go to Workflows<\/a>/)
  })

  it('offers Try again when the platform had a problem', () => {
    expect(text(mainOf(render({ useCase: new ApiError(503, null) })))).toContain('Try again')
  })
})
