import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import older from '../../../../contracts/fixtures/builder/explain.older.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, WorkflowExplained } from '../../api/types'
import { versionOf } from './ExplainPage'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const REPORT = older as WorkflowExplained
const ID = 'uc_01JFASTAPI'
const NOW = new Date('2026-11-16T09:00:00+08:00')

function render(address: string, held: { version: number | null; report: WorkflowExplained | ApiError } | null, me: Me = ALICE): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  if (held) {
    const key = ['use-case', scope, ID, 'explain', held.version, false]
    if (held.report instanceof ApiError) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: held.report, fetchStatus: 'idle' })
    else queryClient.setQueryData(key, held.report)
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[address]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', '’').replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const heading = (html: string) => text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(mainOf(html))?.[1] ?? '')
const buttons = (html: string) => [...mainOf(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

describe('the full page of a report', () => {
  it('has the workflow’s name as its heading, Explain over it, the report, and a way back to the workflow', () => {
    for (const me of [ALICE, BOB]) {
      const html = render(`/workflows/${ID}/explain`, { version: null, report: REPORT }, me)
      expect(heading(html), me.id).toBe('FastAPI release check')
      expect(text(mainOf(html))).toContain('Explain FastAPI release check')
      expect(text(mainOf(html))).toContain('Step by step 8 blocks')
      expect(mainOf(html)).toMatch(/<a[^>]*href="\/workflows\/uc_01JFASTAPI"[^>]*>[\s\S]*The workflow<\/a>/)
      expect(buttons(html)).toEqual([])
    }
  })

  it('titles one version Explain, version N, and asks for it', () => {
    const html = render(`/workflows/${ID}/explain?version=1`, { version: 1, report: REPORT })
    expect(text(mainOf(html))).toContain('Explain, version 1 FastAPI release check')
    expect(text(mainOf(html))).toContain('Version 1. Checked again under today’s rules.')
  })

  it('shows the server’s words where the report would be when there is nothing to explain', () => {
    const words = 'Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no copy of its blocks.'
    const html = render(`/workflows/${ID}/explain`, { version: null, report: new ApiError(409, { detail: words }) })
    expect(text(mainOf(html))).toContain(words)
    expect(buttons(html)).toEqual([])
  })

  it('gives a failed load a reason and Try again', () => {
    const html = render(`/workflows/${ID}/explain`, { version: null, report: new ApiError(500, {}) })
    expect(text(mainOf(html))).toContain('The report could not be loaded.')
    expect(buttons(html)).toEqual(['Try again'])
  })

  it('reads the version from the address, and anything but a whole number from 1 means the version in use', () => {
    expect(versionOf('3')).toBe(3)
    for (const odd of [null, '', '0', '-1', '2.5', 'two', '3; drop', '12345678901']) expect(versionOf(odd), String(odd)).toBeNull()
  })
})
