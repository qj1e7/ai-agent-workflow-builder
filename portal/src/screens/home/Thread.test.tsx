import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { PlannerReply } from '../../api/types'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

function draw(reply: PlannerReply, pending = false): string {
  let thread = threadReducer(EMPTY, { type: 'sent', text: 'what about Redis?' })
  if (!pending) thread = threadReducer(thread, { type: 'answered', reply, typed: 'what about Redis?' })
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Thread thread={thread} now={new Date('2026-11-08T10:00:00+08:00')} page={{ ask: () => undefined, edit: () => undefined }} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

describe('the thread', () => {
  it('shows how a follow-up was read, above the answer', () => {
    const html = draw({ ...(question as PlannerReply), read_as: 'What is the newest version of Redis?' })
    expect(html).toContain('I read this as: What is the newest version of Redis?')
    expect(html.indexOf('I read this as')).toBeLessThan(html.indexOf((question as { text: string }).text))
  })

  it('shows no such line when the request was not rewritten', () => {
    expect(draw({ ...(question as PlannerReply), read_as: null })).not.toContain('I read this as')
  })

  it('says Working on it while the answer is pending, and claims no step', () => {
    const html = draw(question as PlannerReply, true)
    expect(html).toContain('Working on it…')
    expect(html).not.toMatch(/Reading|Checking|Looking/)
  })
})
