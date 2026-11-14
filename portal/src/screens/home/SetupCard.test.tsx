import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import created from '../../../../contracts/fixtures/builder/agent-use-case.off.created.json'
import draftUseCase from '../../../../contracts/fixtures/builder/use-case.draft.json'
import failure from '../../../../contracts/fixtures/runs/failure.json'
import success from '../../../../contracts/fixtures/runs/success.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import setupCross from '../../../../contracts/fixtures/planner/answer.setup_card.cross.json'
import { ApiProvider } from '../../api/context'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { Me, SetupCardReply, UseCaseCreated, UseCaseView } from '../../api/types'
import type { SetUp } from '../../api/workflowQueries'
import { emptyModel, foldWire, type RunModel } from '../run/runModel'
import { BuildingCard, type CardProps } from './Building'
import { BuildPanel } from './BuildPanel'
import { cardFrom } from './card'
import { CardMemoryContext, newCardMemory, type CardKept } from './cardMemory'
import { SetupCard } from './SetupCard'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator'] }
const CREATED = created as UseCaseCreated
const DRAFT = draftUseCase as UseCaseView
const ON: UseCaseView = { ...DRAFT, state: 'on', next_run_at: '2026-11-16T00:00:00Z' }
const SETUP = { ...(setupCard as SetupCardReply), similar: null }
const TYPED = 'Every Friday, sum up the tickets we closed this week'

const session = createDevSession({ getItem: () => ALICE.id, setItem: () => undefined })
const scope = session.cacheScope()

interface World {
  readonly useCase?: UseCaseView
  readonly setUp?: SetUp | null
  readonly kept?: CardKept
}

function render(node: ReactNode, { useCase = DRAFT, setUp = { created: CREATED, at: Date.now() - 60_000, testRunId: null }, kept }: World = {}): string {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  queryClient.setQueryData(keys.useCase(scope, useCase.use_case_id), useCase)
  if (setUp) queryClient.setQueryData(keys.setUp(scope, CREATED.use_case_id), setUp)
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

const card = (reply: SetupCardReply, typed = TYPED) => <SetupCard start={{ form: cardFrom(reply.name, reply.rows, typed, reply.parts), plan: null, draftId: null, similar: reply.similar }} />
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&amp;', '&').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const pill = (html: string) => text(/<span[^>]*data-draft-pill[^>]*>([\s\S]*?)<\/span>/.exec(html)?.[1] ?? '')
const primaries = (html: string) => (html.match(/class="[^"]*_primary_[^"]*"/g) ?? []).length

const passed = foldWire(foldWire(emptyModel, success.slice(0, 8), 'run_01JB8'), [{ run_id: 'run_01JB8', seq: 9, ts: '2026-11-14T03:00:09Z', actor: { kind: 'platform', id: 'platform', display: 'Platform' }, summary: '', kind: 'run_succeeded', data: { outcome: 'test_passed' } }], 'run_01JB8')
const working = foldWire(emptyModel, success.slice(0, 5), 'run_01JB8')
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
  return render(<BuildingCard {...props} />, world)
}

describe('the set-up card before Set up', () => {
  it('is a Draft that asks one question at a time, with Never mind and Set up as its one primary', () => {
    const html = render(card(SETUP))
    expect(pill(html)).toBe('Draft')
    expect(html.match(/data-mark="ask"/g)).toHaveLength(1)
    expect(text(html)).toContain('1 question to answer')
    expect(buttons(html).slice(-2)).toEqual(['Never mind', 'Set up'])
    expect(primaries(html)).toBe(1)
    expect(html, 'Set up is never shown dead: pressed early it points at the question').not.toMatch(/<button[^>]*disabled[^>]*>Set up/)
  })

  it('names the parts Watch, When and Then, in that order, and crosses each part it can’t do', () => {
    const html = render(card(setupCross as SetupCardReply, 'Every Friday at 5pm, sum up the tickets we closed this week in MOCK and colour them by team'))
    const keys = [...html.matchAll(/data-part="([^"]+)"/g)].map((m) => m[1])
    expect(keys).toEqual(['Watch', 'When', 'Then', 'cross-0'])
    expect(text(html)).toContain('Can’t do: “colour them by team” I didn’t follow this part.')
    expect(buttons(html)).toContain('Set up the part I can')
  })

  it('is Dropped after Never mind, saying nothing was set up, with no button', () => {
    const html = render(card(SETUP), { kept: { form: cardFrom(SETUP.name, SETUP.rows, TYPED, SETUP.parts), draft: null, phase: { kind: 'dropped' } } })
    expect(pill(html)).toBe('Dropped')
    expect(text(html)).toContain('Nothing was set up.')
    expect(buttons(html)).toEqual([])
  })

  it('leads with the workflow she already has when the name matches one', () => {
    const html = render(card(setupCard as SetupCardReply), { useCase: { ...ON, use_case_id: 'uc_01JB8', name: 'Weekly summary of closed tickets', schedule: { ...DRAFT.schedule!, day: 'friday', at: '17:00' } } })
    expect(text(html)).toContain('It already runs every Friday at 17:00.')
    expect(buttons(html)).toEqual(['Set up another', 'Open it'])
  })
})

describe('the set-up card after Set up', () => {
  it('shows nothing of the line before the build log says the blocks were added', () => {
    const html = building(null, { setUp: { created: CREATED, at: Date.now() + 60_000, testRunId: null } })
    expect(pill(html)).toBe('Building')
    expect(text(html)).toContain('Starting…')
    expect(html.match(/<li[^>]*data-off="true"/g)?.length, 'each of the four steps waits').toBe(4)
  })

  it('shows the line and the safety checker’s note once the log has replayed, and starts the Tester’s test run', () => {
    const html = building(null)
    expect(pill(html)).toBe('Building')
    expect(html).not.toContain('data-off')
    expect(text(html)).toContain('Added a yes before the ticket.')
    expect(text(html)).toContain('Test run…')
    expect(html, 'the yes the safety checker added is ringed').toContain('data-added="true"')
    expect(buttons(html)).toEqual([])
  })

  it('follows the test run’s own events while it works, with no button to press', () => {
    const html = building(working)
    expect(text(html)).toContain('Test run…')
    expect(html).toContain('data-state="now"')
    expect(buttons(html)).toEqual([])
  })

  it('is Ready once the test run passed up to the yes, says nothing was written, and offers Turn it on', () => {
    const html = building(passed)
    expect(pill(html)).toBe('Ready')
    expect(text(html)).toContain('Test run passed up to the yes. Nothing was written.')
    expect(buttons(html)).toEqual(['Turn it on'])
    expect(primaries(html)).toBe(1)
    expect(text(html), 'the write was never made').toContain('Nothing written')
  })

  it('goes back to a Draft when the test run stopped, with why, Open and Test again', () => {
    const html = building(stopped)
    expect(pill(html)).toBe('Draft')
    expect(text(html)).toContain('The test run stopped. An agent could not finish its work.')
    expect(buttons(html)).toEqual(['Open the test run', 'Test again'])
  })

  it('says Test again when the platform would not start the test run', () => {
    const html = building(null, {}, { problem: 'Could not start the test run. The platform is busy.' })
    expect(text(html)).toContain('Could not start the test run.')
    expect(buttons(html)).toEqual(['Test again'])
  })

  it('never waits on a test run it can’t start: with the set-up gone from this visit, it says the draft is saved and opens it', () => {
    const html = building(null, { setUp: null })
    expect(pill(html)).toBe('Draft')
    expect(text(html)).toContain('Saved as a draft. Open it to test it and turn it on.')
    expect(text(html)).not.toContain('Test run…')
    expect(buttons(html)).toEqual(['Open LangGraph release check'])
  })

  it('says On only once the platform says the workflow is on, with its first run', () => {
    const ready = building(passed, { useCase: DRAFT }, { turning: true })
    expect(pill(ready), 'pressing Turn it on is not On').toBe('Ready')
    const html = building(passed, { useCase: ON })
    expect(pill(html)).toBe('On')
    expect(text(html)).toMatch(/On\. First run Mon 16 Nov, 8:00\./)
    expect(buttons(html)).toEqual([])
  })
})

describe('Building in n8n', () => {
  it('draws the blocks, says what the builder did and lists the checks, with the footnote that holds today', () => {
    const html = render(<BuildPanel id={CREATED.use_case_id} />)
    expect(text(html)).toContain('Building in n8n')
    expect(text(html)).toContain('Test run…')
    expect(html).toContain('<svg')
    expect(text(html)).toContain('The blocks fit together.')
    expect(text(html)).toContain('Every write waits for a yes.')
    expect(text(html)).toContain('The builder saves a draft. It can’t publish by itself.')
    expect(text(html)).not.toContain('Only our blocks')
  })

  it('says On, version 1, published in n8n, only once the platform says so', () => {
    expect(text(render(<BuildPanel id={CREATED.use_case_id} />, { useCase: ON }))).toContain('On. Version 1, published in n8n.')
  })

  it('never says n8n for a workflow the platform didn’t lay out there', () => {
    const shared = { ...CREATED, n8n_workflow_id: null, build_log: [], blocks: [] }
    const html = text(render(<BuildPanel id={CREATED.use_case_id} />, { setUp: { created: shared, at: 0, testRunId: null } }))
    expect(html).not.toContain('n8n')
  })
})
