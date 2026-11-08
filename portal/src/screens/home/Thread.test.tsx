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
  it('shows a status region while the answer is pending, and claims no step', () => {
    const html = draw(question as PlannerReply, true)
    expect(html).toContain('role="status"')
    expect(html).not.toMatch(/Reading|Checking|Looking/)
  })
})
