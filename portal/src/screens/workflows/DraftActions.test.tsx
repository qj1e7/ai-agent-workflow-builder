import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import draft from '../../../../contracts/fixtures/builder/use-case.draft.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { UseCaseView } from '../../api/types'
import { DraftActions } from './DraftActions'
import type { LastRun, Viewer } from './workflow'

const ALICE: Viewer = { id: 'alice', operator: true, approver: false }
const BOB: Viewer = { id: 'bob', operator: false, approver: true }
const DRAFT = draft as UseCaseView
const PASSED: LastRun = { run_id: 'run_1', state: 'succeeded', at: '2026-11-14T03:00:00Z', test: true, declined_by: null, decline_reason: null, approved_by: [], proposed: 1, written: 0, tickets: true, you_can_decide: false, retryable: false, reason: null, outcome: 'test_passed' }

const draw = (useCase: UseCaseView, viewer: Viewer = ALICE) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <DraftActions useCase={useCase} viewer={viewer} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

describe('a draft on its page and in the panel', () => {
  it('offers a test run before anything else, and says it runs only as a test until it is turned on', () => {
    const html = draw(DRAFT)
    expect(buttons(html)).toEqual(['Test run'])
    expect(text(html)).toContain('A draft. It runs only as a test, which writes nothing, until you turn it on after a test run passes.')
  })

  it('offers Turn it on once a test run passed, as the set-up card does', () => {
    const html = draw({ ...DRAFT, last_run: PASSED })
    expect(buttons(html)).toEqual(['Test run', 'Turn it on'])
    expect(text(html)).toContain('Test run passed up to the yes. Nothing was written.')
  })

  it('is nothing for a workflow that is on, and nothing for someone who isn’t an Operator', () => {
    expect(draw({ ...DRAFT, state: 'on', last_run: PASSED })).toBe('')
    expect(draw(DRAFT, BOB)).toBe('')
  })
})
