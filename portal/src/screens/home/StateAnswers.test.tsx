import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import stopped from '../../../../contracts/fixtures/builder/use-case.stopped.json'
import checkWorkflows from '../../../../contracts/fixtures/planner/answer.check_workflows.json'
import needsMe from '../../../../contracts/fixtures/planner/answer.needs_me.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { HomeOut, Me, PlannerReply, UseCaseView, WatchlistView } from '../../api/types'
import { OpensInPanel } from '../../ui/sidePanel'
import { Thread } from './Thread'
import { EMPTY, threadReducer, type Thread as ThreadState } from './threadState'
import { needsTotal } from './home'
import { countLine } from '../software/software'
import { WORKFLOWS_SHOWN } from './StateAnswers'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const NOW = new Date('2026-11-05T15:00:00+08:00')
const PAGE = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const WATCHLIST = statuses as WatchlistView
const STOPPED = stopped as UseCaseView

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const many = (n: number): UseCaseView[] => Array.from({ length: n }, (_, i) => ({ ...STOPPED, use_case_id: `uc_${String(i)}`, name: `Workflow ${String(i)}` }))

function draw(thread: ThreadState, { me = ALICE, home, useCases = [STOPPED], watchlist = WATCHLIST }: { me?: Me; home?: HomeOut; useCases?: UseCaseView[]; watchlist?: WatchlistView } = {}): string {
  const session = createDevSession({ getItem: () => me.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  client.setQueryData(['me', scope], me)
  client.setQueryData(['dev-users'], [ALICE, BOB])
  client.setQueryData(['home', scope], home ?? (me.id === 'bob' ? bobHome : aliceHome))
  client.setQueryData(['use-cases', scope], useCases)
  client.setQueryData(['watchlist', scope], watchlist)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <OpensInPanel.Provider value={{ shown: null, open: () => undefined, show: () => undefined }}>
            <Thread thread={thread} now={NOW} page={PAGE} />
          </OpensInPanel.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const answered = (reply: PlannerReply) => threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'asked' }), { type: 'answered', reply, typed: 'asked' })
const behind = threadReducer(EMPTY, { type: 'asked_behind', text: 'Which software is behind?' })

describe('the Needs card (What needs me?)', () => {
  const html = draw(answered(needsMe as PlannerReply))

  it('heads the card with the count in the sketch’s words, over the same Do now and Set up rows as Home', () => {
    expect(text(html)).toContain(`${String(needsTotal(aliceHome as HomeOut))} things need you`)
    expect(text(html)).toMatch(/Do now[\s\S]*Software watchlist stopped[\s\S]*Set up/)
    expect(html.match(/data-home-item=/g)).toHaveLength(needsTotal(aliceHome as HomeOut))
  })

  it('opens a row beside the chat, one click, and draws no button of its own on a row', () => {
    expect(html).toMatch(/<button[^>]*data-opens="run:run_01JB9"/)
    expect(html).toMatch(/<button[^>]*data-opens="connection:github"/)
    expect(html.match(/<button/g)?.length).toBe(html.match(/data-opens=/g)?.length)
  })

  it('says one thing when nothing needs the person, with no card', () => {
    const calm: HomeOut = { ...(aliceHome as HomeOut), stopped: [], stopped_total: 0, replied: [], addresses: [], connections: [], waiting_on_others: [], waiting_on_others_total: 0 }
    expect(needsTotal(calm)).toBe(0)
    const shown = draw(answered(needsMe as PlannerReply), { home: calm })
    expect(shown).not.toContain('<section')
  })
})

describe('the Workflows card (show my workflows)', () => {
  const reply = checkWorkflows as PlannerReply

  it('shows a few rows, each with when it runs and its state, and no more than the cap', () => {
    const html = draw(answered(reply), { useCases: many(WORKFLOWS_SHOWN + 3) })
    expect(html.match(/data-opens="workflow:/g)).toHaveLength(WORKFLOWS_SHOWN)
    expect(text(html)).toContain(`Workflows ${String(WORKFLOWS_SHOWN + 3)}`)
  })

  it('ends with a way to the whole list, opened beside the chat, only when rows are left out', () => {
    expect(draw(answered(reply), { useCases: many(WORKFLOWS_SHOWN + 1) })).toMatch(/<button[^>]*data-opens="workflows:"[^>]*>See all workflows/)
    expect(text(draw(answered(reply), { useCases: many(WORKFLOWS_SHOWN) }))).not.toContain('See all workflows')
  })
})

describe('the behind card (Which software is behind?)', () => {
  it('counts the software with a newer version the way the Software page does, and opens each row beside the chat', () => {
    const html = draw(behind)
    expect(text(html)).toContain('3 have a newer version')
    expect(html.match(/data-opens="software:/g)).toHaveLength(3)
    expect(text(html)).toContain('LangGraph 1.2.14 → 1.2.16 · checked by Software watchlist Newer out')
    expect(text(html)).not.toContain('n8n')
  })

  it('ends with See the watchlist, which opens the watchlist beside the chat', () => {
    expect(draw(behind)).toMatch(/<button[^>]*data-opens="watchlist:"[^>]*>See the watchlist/)
  })

  it('says so, with no card, when nothing has a newer version', () => {
    const current: WatchlistView = { ...WATCHLIST, software: WATCHLIST.software.filter((row) => row.status === 'up_to_date') }
    const html = draw(behind, { watchlist: current })
    expect(html).not.toContain('<section')
    expect(text(html)).toContain(`${countLine(current.software) ?? 'a count line'}.`)
  })

  it('is an answer of its own: marked as one, and the person’s words come first', () => {
    const html = draw(behind)
    expect(html).toContain('data-answer="true"')
    expect(text(html)).toContain('You: Which software is behind? Planner:')
  })
})
