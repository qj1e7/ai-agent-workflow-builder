import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import abilities from '../../../../contracts/fixtures/planner/answer.abilities.json'
import ideas from '../../../../contracts/fixtures/planner/answer.ideas.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import { ApiProvider } from '../../api/context'
import { capabilitiesKey } from '../../api/plannerQueries'
import { createDevSession } from '../../api/session'
import type { Me, PlannerReply } from '../../api/types'
import { clicksByLabel, pressByLabel } from '../../ui/testing'
import { Answer, type Page } from './AnswerCards'

vi.mock('../../ui/Button', async (importOriginal) => (await import('../../ui/testing')).recordingButtons(await importOriginal()))

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

function failedLoad(reply: PlannerReply) {
  clicksByLabel.clear()
  const reads: string[] = []
  const platform = (input: RequestInfo | URL, init?: RequestInit) => {
    reads.push(new URL(new Request(input, init).url).pathname)
    return Promise.resolve(new Response(JSON.stringify(capabilities), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  }
  const session = createDevSession(null)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false } } })
  client.setQueryData(['me', session.cacheScope()], ALICE)
  client.getQueryCache().build(client, { queryKey: capabilitiesKey(session.cacheScope()) }).setState({ status: 'error', error: new Error('no answer'), fetchStatus: 'idle' })
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={platform} origin="http://portal.test" baseUrl="http://portal.test">
        <MemoryRouter>
          <Answer reply={reply} typed="What can you do?" page={PAGE} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
  return { html, reads, client, scope: session.cacheScope() }
}

describe('a Planner answer whose list failed to load', () => {
  for (const [name, reply, sentence] of [
    ['what I can do', abilities as PlannerReply, 'I couldn’t load what I can do just now.'],
    ['the ideas', ideas as PlannerReply, 'I couldn’t load the ideas just now.'],
  ] as const) {
    it(`keeps its sentence for ${name}, and Try again reads the list again`, async () => {
      const { html, reads, client, scope } = failedLoad(reply)
      expect(text(html)).toContain(sentence)
      expect(reads).toEqual([])
      pressByLabel('Try again')
      await vi.waitFor(() => expect(client.getQueryState(capabilitiesKey(scope))?.status).toBe('success'))
      expect(reads).toEqual(['/api/v1/capabilities'])
    })
  }
})
