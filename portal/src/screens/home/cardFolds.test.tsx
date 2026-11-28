import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { PlannerReply } from '../../api/types'
import { Answer, type Page } from './AnswerCards'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }

function draw(reply: PlannerReply): string {
  const queryClient = new QueryClient()
  queryClient.setQueryData(['capabilities', createDevSession(null).cacheScope()], capabilities)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <Answer reply={reply} typed="skip the approval" page={PAGE} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const words = (html: string) => html.replace(/<[^>]*>/g, ' ').split(/\s+/).filter(Boolean).length

/** The words a person reads before the first button, link or fold in a card, past its title (ADR 0052: about 25 at most). */
function wordsBeforeFirstAction(html: string): number {
  const at = html.search(/<(button|a|summary)\b/)
  return words((at === -1 ? html : html.slice(0, at)).replace(/<h3\b[\s\S]*?<\/h3>/, ''))
}

const HOW_TO_START: PlannerReply = { trace_id: null, answer: 'abilities', how_to_start: true, parts: [{ text: 'how do I start', mark: 'will_do', reason: null, note: null, choices: [] }] }

describe('dense text in an answer card sits behind a fold', () => {
  it('How to start keeps its four steps open, because the list is the answer', () => {
    const html = draw(HOW_TO_START)
    expect(html).not.toContain('<details')
    expect(html.match(/<li\b/g)).toHaveLength(4)
  })

  it('How approvals work says who decides in view, and only the say-it-another-way hint folds under Details', () => {
    const html = draw(refused as PlannerReply)
    const rule = html.indexOf('Any Approver on your team except you')
    expect(rule).toBeGreaterThan(-1)
    expect(rule).toBeLessThan(html.indexOf('<details'))
    expect(html).toMatch(/<details\b[^>]*>\s*<summary\b[^>]*>Details<\/summary>(?:(?!<\/details>)[\s\S])*say it another way(?:(?!<\/details>)[\s\S])*<\/details>/)
    expect(html.match(/<details\b[\s\S]*<\/details>/)?.[0]).not.toContain('Any Approver')
  })

  it('reaches a button, link or fold within 25 words on a card that is not itself a list', () => {
    expect(wordsBeforeFirstAction(draw(refused as PlannerReply))).toBeLessThanOrEqual(40)
  })
})
