import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import editChoices from '../../../../contracts/fixtures/planner/answer.edit.choices.json'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { PlannerReply } from '../../api/types'
import { newCardMemory, type CardMemory } from './cardMemory'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

function draw(reply: PlannerReply, pending = false): string {
  let thread = threadReducer(EMPTY, { type: 'sent', text: 'what about Redis?' })
  if (!pending) thread = threadReducer(thread, { type: 'answered', reply, typed: 'what about Redis?' })
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Thread thread={thread} now={new Date('2026-11-08T10:00:00+08:00')} page={{ ask: () => undefined, edit: () => undefined, box: () => undefined }} />
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

describe('“it” in a request', () => {
  it('means the workflow she picked on the edit card before, when that card offered several', () => {
    const choices = editChoices as PlannerReply
    let thread = threadReducer(EMPTY, { type: 'sent', text: 'make the friday one daily' })
    thread = threadReducer(thread, { type: 'answered', reply: choices, typed: 'make the friday one daily' })
    thread = threadReducer(thread, { type: 'sent', text: 'make it daily' })
    thread = threadReducer(thread, { type: 'answered', reply: choices, typed: 'make it daily' })
    const memories = new Map<number, CardMemory>()
    const memory = (id: number) => memories.get(id) ?? memories.set(id, newCardMemory()).get(id) ?? newCardMemory()
    const first = thread.messages.find((message) => message.kind === 'reply')?.id ?? 0
    memory(first).edit.keep({ picks: { useCaseId: 'uc_01JC2', day: null, at: null }, phase: { kind: 'open' } })
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
          <MemoryRouter>
            <Thread thread={thread} now={new Date('2026-11-08T10:00:00+08:00')} page={{ ask: () => undefined, edit: () => undefined, box: () => undefined }} memory={memory} />
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>,
    )
    expect(html.match(/Change Weekly closed-ticket summary/g), 'both cards change the workflow she picked').toHaveLength(2)
  })
})
