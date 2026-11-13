import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import editChoices from '../../../../contracts/fixtures/planner/answer.edit.choices.json'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PlannerReply } from '../../api/types'
import { newCardMemory, type CardMemory } from './cardMemory'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }

function draw(reply: PlannerReply, pending = false, me?: Me): string {
  let thread = threadReducer(EMPTY, { type: 'sent', text: 'what about Redis?' })
  if (!pending) thread = threadReducer(thread, { type: 'answered', reply, typed: 'what about Redis?' })
  const session = createDevSession(null)
  const client = new QueryClient()
  if (me) client.setQueryData(['me', session.cacheScope()], me)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Thread thread={thread} now={new Date('2026-11-08T10:00:00+08:00')} page={{ ask: () => undefined, edit: () => undefined, box: () => undefined }} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const said = (html: string) => /<li[^>]*data-answer[^>]*>([\s\S]*)<\/li>/.exec(html)?.[1] ?? ''

describe('the thread', () => {
  it('shows a status region while the answer is pending, and claims no step', () => {
    const html = draw(question as PlannerReply, true)
    expect(html).toContain('role="status"')
    expect(html).not.toMatch(/Reading|Checking|Looking/)
  })

  it('shows only the Planner’s thinking face and three dots while the answer is pending, with no words on screen', () => {
    const pending = /<li[^>]*>(?:(?!<\/li>)[\s\S])*_dots_[\s\S]*?<\/li>/.exec(draw(question as PlannerReply, true))?.[0] ?? ''
    expect(pending).toMatch(/<svg[^>]*width="30"/)
    expect(pending.match(/<i><\/i>/g)).toHaveLength(3)
    expect(text(pending)).toBe('')
  })

  it('keeps “You:” for a screen reader on the person’s own message', () => {
    expect(draw(question as PlannerReply)).toMatch(/<span class="visually-hidden">You: <\/span>what about Redis\?/)
  })

  it('names the Planner on an answer that is only words, beside its 30 px face, with a colon only a screen reader hears', () => {
    const answer = said(draw({ ...(question as PlannerReply), about_software: [] } as PlannerReply, false, ALICE))
    expect(answer).toMatch(/<svg[^>]*width="30"/)
    expect(answer).toMatch(/>Planner<span class="visually-hidden">:<\/span><\/span>/)
    expect(text(answer)).toMatch(/^Planner : LangGraph is behind\./)
  })

  it('leads a card with the sentence when a question answer offers an Operator actions, not a bubble with buttons in it', () => {
    const answer = said(draw(question as PlannerReply, false, ALICE))
    expect(answer).not.toMatch(/>Planner</)
    expect(answer).toMatch(/<p>LangGraph is behind\.[^<]*<\/p><section[^>]*>/)
    expect(answer).toMatch(/<h3 id="[^"]*">LangGraph<\/h3>/)
  })

  it('leads a card with its sentence and no name on screen, which only a screen reader hears', () => {
    const answer = said(draw(refused as PlannerReply))
    expect(answer).toMatch(/<span class="visually-hidden">Planner: <\/span>/)
    expect(answer).toContain('How approvals work')
    expect(answer).not.toMatch(/>Planner</)
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
