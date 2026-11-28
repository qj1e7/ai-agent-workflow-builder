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
  it('How to start leads with its one sentence set, and the numbered steps fold away, still read in order', () => {
    const html = draw(HOW_TO_START)
    expect(wordsBeforeFirstAction(html)).toBeLessThanOrEqual(25)
    expect(html).toMatch(/<details\b[^>]*>\s*<summary\b[^>]*>Show the steps<\/summary>[\s\S]*<ol\b[\s\S]*<\/ol>[\s\S]*<\/details>/)
    expect(html.match(/<li\b/g)).toHaveLength(4)
  })

  it('How approvals work quotes what they asked first, and the rule folds under Details', () => {
    const html = draw(refused as PlannerReply)
    expect(wordsBeforeFirstAction(html)).toBeLessThanOrEqual(25)
    expect(html).toMatch(/<details\b[^>]*>\s*<summary\b[^>]*>Details<\/summary>[\s\S]*Nobody approves their own work[\s\S]*say it another way[\s\S]*<\/details>/)
  })
})
