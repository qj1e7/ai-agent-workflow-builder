import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

vi.mock('react', async (importOriginal) => ({ ...(await importOriginal<typeof import('react')>()), useEffect: (effect: () => void) => void effect() }))
import created from '../../../../contracts/fixtures/builder/agent-use-case.off.created.json'
import draftUseCase from '../../../../contracts/fixtures/builder/use-case.draft.json'
import failure from '../../../../contracts/fixtures/runs/failure.json'
import success from '../../../../contracts/fixtures/runs/success.json'
import { ApiProvider } from '../../api/context'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { Me, RunView, UseCaseCreated, UseCaseView, WatchlistView } from '../../api/types'
import type { Made, SetUp } from '../../api/workflowQueries'
import { emptyModel, foldWire, type RunModel } from '../run/runModel'
import { BuildingCard, type CardProps } from './Building'
import { CardMemoryContext, newCardMemory, type CardKept } from './cardMemory'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator'] }
const CREATED = created as UseCaseCreated
const DRAFT = draftUseCase as UseCaseView
const ON: UseCaseView = { ...DRAFT, state: 'on', next_run_at: '2026-11-16T00:00:00Z' }

const session = createDevSession({ getItem: () => ALICE.id, setItem: () => undefined })
const scope = session.cacheScope()

interface World {
  readonly useCase?: UseCaseView
  /** The test run as GET /api/v1/runs/{id} answers it. */
  readonly run?: RunView
  /** The workflow's read failed. */
  readonly unread?: boolean
  readonly watched?: WatchlistView
  readonly made?: { readonly key: string; readonly made: Made }
  readonly setUp?: SetUp | null
  readonly kept?: CardKept
}

const HELD: SetUp = { created: CREATED, at: Date.now() - 60_000, testRunId: null, testKey: 'k1', testAsked: null }

function render(node: ReactNode, { useCase = DRAFT, setUp = HELD, kept, unread = false, watched, made, run }: World = {}): string {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  if (run) queryClient.setQueryData(keys.run(scope, run.run_id), run)
  if (unread) queryClient.getQueryCache().build(queryClient, { queryKey: keys.useCase(scope, useCase.use_case_id) }).setState({ status: 'error', error: new Error('no answer'), fetchStatus: 'idle' })
  else queryClient.setQueryData(keys.useCase(scope, useCase.use_case_id), useCase)
  if (setUp) queryClient.setQueryData(keys.setUp(scope, CREATED.use_case_id), setUp)
  if (watched) queryClient.setQueryData(keys.watchlist(scope), watched)
  if (made) queryClient.setQueryData(keys.made(scope, made.key), made.made)
  const memory = newCardMemory()
  if (kept) memory.keep(kept)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>{node}</CardMemoryContext.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}


const passed = foldWire(foldWire(emptyModel, success.slice(0, 8), 'run_01JB8'), [{ run_id: 'run_01JB8', seq: 9, ts: '2026-11-14T03:00:09Z', actor: { kind: 'platform', id: 'platform', display: 'Platform' }, summary: '', kind: 'run_succeeded', data: { outcome: 'test_passed' } }], 'run_01JB8')
const stopped = foldWire(emptyModel, failure, failure[0]?.run_id ?? '')

function building(test: RunModel | null, world: World = {}, more: Partial<CardProps> = {}): string {
  const props: CardProps = {
    useCaseId: CREATED.use_case_id,
    title: 'LangGraph release check',
    parts: [{ key: 'When', mark: 'ok', label: 'When', body: 'Every Monday at 8:00' }],
    newAgents: [],
    draftKept: false,
    test,
    runId: test === null ? null : 'run_01JB8',
    problem: null,
    starting: false,
    turning: false,
    onReplayed: () => undefined,
    onTestAgain: () => undefined,
    onTurnOn: () => undefined,
    ...more,
  }
  return render(<BuildingCard {...props} />, { setUp: { ...HELD, testRunId: test === null ? null : 'run_01JB8' }, ...world })
}


describe('Turn on after a passing test run (effects run during the render)', () => {
  it('turns the workflow on once the test passed and it is still a draft', () => {
    const calls: unknown[] = []
    building(passed, { useCase: DRAFT }, { onTurnOn: (...args) => calls.push(args) })
    expect(calls).toHaveLength(1)
  })

  it('does not turn it on while turning, after a problem, once it is on, or when the test stopped', () => {
    const calls: unknown[] = []
    const onTurnOn = (...args: unknown[]) => calls.push(args)
    building(passed, { useCase: DRAFT }, { onTurnOn, turning: true })
    building(passed, { useCase: DRAFT }, { onTurnOn, problem: 'Could not turn it on.' })
    building(passed, { useCase: ON }, { onTurnOn })
    building(stopped, { useCase: DRAFT }, { onTurnOn })
    expect(calls).toHaveLength(0)
  })
})

describe('The card when the test run stopped', () => {
  const stoppedWith = (retryable: boolean): RunModel =>
    foldWire(emptyModel, failure.map((event) => (event.kind === 'run_failed' ? { ...event, data: { ...event.data, retryable } } : event)), failure[0]?.run_id ?? '')
  const labels = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => (m[1] ?? '').replace(/<[^>]*>/g, '').trim())

  it('offers Try again and Open the workflow when the platform says the stop can be retried', () => {
    const html = building(stoppedWith(true), { useCase: DRAFT })
    expect(labels(html)).toEqual(expect.arrayContaining(['Try again', 'Open the workflow']))
  })

  it('offers only Open the workflow, as the primary action, when the stop cannot be retried', () => {
    const html = building(stoppedWith(false), { useCase: DRAFT })
    expect(labels(html)).not.toContain('Try again')
    const open = [...html.matchAll(/<a\b([^>]*)>[^<]*Open the workflow/g)][0]?.[1] ?? ''
    expect(open).toMatch(/primary/)
  })
})
