import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import waiting from '../../../../contracts/fixtures/views/success.awaiting_approval.json'
import { App } from '../../App'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ApprovalItem, HomeOut, Me, RunView, StoppedItem, UseCaseView } from '../../api/types'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const NOW = new Date('2026-11-04T15:00:00+08:00')
const ids = Array.from({ length: 11 }, (_, i) => `uc_${String(i + 1).padStart(2, '0')}`)
const useCases: UseCaseView[] = ids.map((id) => ({ ...(agentUseCase as UseCaseView), use_case_id: id, name: `Workflow ${id}` }))
const at = (i: number) => `2026-11-03T${String(10 + i).padStart(2, '0')}:00:00Z`
const runs: RunView[] = [
  { ...(failed as RunView), use_case_id: ids[0] ?? '', run_id: 'run_stopped' },
  ...ids.slice(1).map((id, i) => ({ ...(waiting as RunView), use_case_id: id, run_id: `run_${id}`, started_at: at(i), you_can_decide: true })),
]
const approval = (bobHome as HomeOut).approvals[0] as ApprovalItem
const stopped = (aliceHome as HomeOut).stopped[0] as StoppedItem
const home: HomeOut = {
  ...(aliceHome as HomeOut),
  stopped: [{ ...stopped, run_id: 'run_stopped', use_case_id: ids[0] ?? '' }],
  stopped_total: 1,
  approvals: ids
    .slice(1)
    .map((id, i) => ({ ...approval, run_id: `run_${id}`, approval_id: `apr_${id}`, use_case_id: id, use_case_name: `Workflow ${id}`, started_by: 'carol', started_by_name: 'Carol', started_at: at(i) }))
    .reverse(),
  approvals_total: 10,
  confirmations: [],
}

function render(): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  queryClient.setQueryData(['dev-users'], [ALICE])
  queryClient.setQueryData(['runs', scope], runs)
  queryClient.setQueryData(['home', scope], home)
  queryClient.setQueryData(['use-cases', scope], useCases)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[{ pathname: '/workflows' }]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const rowOf = (html: string, id: string) => new RegExp(`<li[^>]*data-workflow-id="${id}"[\\s\\S]*?</li>`).exec(html)?.[0] ?? ''

it('with more requests than Needs you shows, a request cut from it keeps its row button', () => {
  const html = render()
  const shown = [...html.matchAll(/data-home-item="([^"]+)"/g)].map((m) => m[1])
  const unreachable = home.approvals
    .filter((item) => !shown.includes(`approval:${item.approval_id}`) && !rowOf(html, item.use_case_id).includes(`href="/runs/${item.run_id}"`))
    .map((item) => `${item.use_case_name} (${item.run_id}): row is ${rowOf(html, item.use_case_id) ? 'there, with no button' : 'missing'}`)
  expect(unreachable).toEqual([])
})
