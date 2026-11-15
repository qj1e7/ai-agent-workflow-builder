import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../../contracts/fixtures/builder/use-case.json'
import peopleList from '../../../../../contracts/fixtures/people/list.json'
import statuses from '../../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../../api/context'
import { createDevSession } from '../../../api/session'
import type { Me, PersonOut, UseCaseView, WatchlistView } from '../../../api/types'
import { InChat } from '../../../ui/fromChat'
import type { PanelItem } from '../../../ui/sidePanel'
import { SoftwareRoute } from '../../software/SoftwarePage'
import { stateOf } from '../../software/software'
import type { LastRun } from '../../workflows/workflow'
import { WorkflowsPage } from '../../workflows/WorkflowsPage'
import { SidePanel } from '../SidePanel'
import { BehindAnswer, CheckWorkflowsAnswer } from '../StateAnswers'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob'].includes(person.id))
const NOW = new Date('2026-11-05T15:00:00+08:00')

const STATUSES = statuses as WatchlistView
const [FIRST] = STATUSES.software
if (!FIRST) throw new Error('the statuses fixture has rows')
/** Every state a software can be in: the fixture's, plus one GitHub can't find and one up to date with no version of ours known. */
const EVERY_SOFTWARE: WatchlistView = {
  ...STATUSES,
  software: [
    ...STATUSES.software,
    { ...FIRST, id: 'sw_gone', name: 'LangServe', status: 'cant_check', not_found: true },
    { ...FIRST, id: 'sw_watching', name: 'Vite', status: 'up_to_date', our_version: null, newest_version: '7.3.6' },
  ],
}
const NOT_CHECKED_ON_ITS_OWN: WatchlistView = { ...EVERY_SOFTWARE, schedule: null }

const lr = (change: Partial<LastRun>): LastRun => ({ run_id: 'run_x', state: 'succeeded', at: '2026-11-05T01:00:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: false, you_can_decide: false, retryable: false, reason: null, ...change })
const AGENT = agentUseCase as UseCaseView
const SCHEDULE = (watchlistUseCase as UseCaseView).schedule
const flow = (id: string, change: Partial<UseCaseView>): UseCaseView => ({ ...AGENT, use_case_id: id, name: `Workflow ${id}`, ...change })
/** Every state a workflow row says: no runs, paused, stopped, a stopped test run, waiting for a yes, declined, written, and the Software watchlist. */
const EVERY_WORKFLOW: UseCaseView[] = [
  flow('uc_new', { schedule: null }),
  flow('uc_paused', { state: 'paused', schedule: SCHEDULE, last_run: lr({}) }),
  flow('uc_stopped', { schedule: SCHEDULE, last_run: lr({ state: 'failed', retryable: true, reason: 'AgentError' }) }),
  flow('uc_test', { last_run: lr({ state: 'failed', test: true, reason: 'AgentError' }) }),
  flow('uc_waiting', { schedule: SCHEDULE, last_run: lr({ state: 'awaiting_approval', proposed: 2, tickets: true }) }),
  flow('uc_declined', { last_run: lr({ state: 'rejected', declined_by: 'bob', decline_reason: 'Not this week' }) }),
  flow('uc_written', { last_run: lr({ written: 1, tickets: true, approved_by: ['bob'] }) }),
  { ...(watchlistUseCase as UseCaseView), last_run: lr({ state: 'awaiting_approval', proposed: 1, tickets: true }) },
]

function render(page: ReactNode, { watchlist = EVERY_SOFTWARE, path = '/' }: { watchlist?: WatchlistView; path?: string } = {}): string {
  const session = createDevSession({ getItem: () => ALICE.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  client.setQueryData(['me', scope], ALICE)
  client.setQueryData(['dev-users'], [ALICE, BOB])
  client.setQueryData(['people', scope], TEAM)
  client.setQueryData(['watchlist', scope], watchlist)
  client.setQueryData(['use-cases', scope], EVERY_WORKFLOW)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>{page}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const panel = (item: PanelItem, watchlist?: WatchlistView) =>
  render(
    <InChat.Provider value>
      <SidePanel item={item} now={NOW} narrow={false} onClose={() => undefined} onOpen={() => undefined} />
    </InChat.Provider>,
    watchlist ? { watchlist } : {},
  )

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

/** Each row's id and what it says, in the order shown. */
function rowsIn(html: string, attribute: 'data-software-id' | 'data-workflow-id'): [string, string][] {
  return [...html.matchAll(new RegExp(`<li[^>]*${attribute}="([^"]+)"[^>]*>([\\s\\S]*?)</li>`, 'g'))].map((match) => [match[1] ?? '', text(match[2] ?? '')])
}

describe('a list in the chat says what its page says', () => {
  it('lists the watchlist in the panel row for row as the Watchlist page does, urgent first, for every state', () => {
    for (const watchlist of [EVERY_SOFTWARE, NOT_CHECKED_ON_ITS_OWN]) {
      const page = rowsIn(render(<SoftwareRoute now={NOW} />, { watchlist, path: '/software' }), 'data-software-id')
      expect(page).toHaveLength(watchlist.software.length)
      expect(new Set(watchlist.software.map((row) => stateOf(row).words))).toEqual(new Set(['Can’t check', 'Can’t find', 'Newer out', 'Watching', 'Up to date']))
      expect(rowsIn(panel({ kind: 'watchlist' }, watchlist), 'data-software-id')).toEqual(page)
    }
  })

  it('draws the behind card’s rows as the Watchlist page draws them', () => {
    const page = new Map(rowsIn(render(<SoftwareRoute now={NOW} />, { path: '/software' }), 'data-software-id'))
    const card = rowsIn(render(<BehindAnswer now={NOW} say={() => undefined} />), 'data-software-id')
    expect(card.map(([, said]) => said.endsWith('Newer out'))).toEqual([true, true, true])
    for (const [id, said] of card) expect(said).toBe(page.get(id))
  })

  it('lists the workflows in the panel row for row as the Workflows page does, for every state', () => {
    const page = rowsIn(render(<WorkflowsPage heading="Workflows" now={NOW} />, { path: '/workflows' }), 'data-workflow-id')
    expect(page).toHaveLength(EVERY_WORKFLOW.length)
    const said = page.map(([, row]) => row).join(' | ')
    for (const state of ['no runs yet On', 'Paused', 'Stopped', 'Stopped Test run', 'waiting for a yes Waiting for a yes', 'declined by Bob', 'approved by Bob On']) expect(said).toContain(state)
    expect(rowsIn(panel({ kind: 'workflows' }), 'data-workflow-id')).toEqual(page)
  })

  it('draws the Workflows card’s rows as the Workflows page draws them', () => {
    const page = rowsIn(render(<WorkflowsPage heading="Workflows" now={NOW} />, { path: '/workflows' }), 'data-workflow-id')
    const card = rowsIn(render(<CheckWorkflowsAnswer useCaseId={null} now={NOW} say={() => undefined} />), 'data-workflow-id')
    expect(card).toEqual(page.slice(0, card.length))
    expect(card.length).toBeGreaterThan(0)
  })
})
