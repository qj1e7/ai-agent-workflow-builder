import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import created from '../../../../contracts/fixtures/builder/agent-use-case.off.created.json'
import draftUseCase from '../../../../contracts/fixtures/builder/use-case.draft.json'
import failure from '../../../../contracts/fixtures/runs/failure.json'
import failedView from '../../../../contracts/fixtures/views/failure.final.json'
import success from '../../../../contracts/fixtures/runs/success.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import setupCross from '../../../../contracts/fixtures/planner/answer.setup_card.cross.json'
import simulated from '../../../../contracts/fixtures/builder/drafted.simulated.json'
import { ApiProvider } from '../../api/context'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import planUseOne from '../../../../contracts/fixtures/cards/plan.use-one.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import type { FindOut, DraftedWorkflowView, Me, PlanOut, RunView, SetupCardReply, SimulationView, UseCaseCreated, UseCaseSimulationView, UseCaseView, WatchlistView } from '../../api/types'
import type { Made, SetUp } from '../../api/workflowQueries'
import { emptyModel, foldWire, type RunModel } from '../run/runModel'
import { BuildingCard, type CardProps } from './Building'
import { BuildPanel } from './BuildPanel'
import { cardFrom, planView, taskWithoutSchedule } from './card'
import { PartsList } from './PartsList'
import { CardMemoryContext, newCardMemory, type CardKept } from './cardMemory'
import { frozenParts, SetupCard } from './SetupCard'

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
  /** The test run as GET /api/v1/runs/{id} answers it. */
  readonly run?: RunView
  /** The workflow's read failed. */
  readonly unread?: boolean
  readonly watched?: WatchlistView
  readonly made?: { readonly key: string; readonly made: Made }
  readonly setUp?: SetUp | null
  readonly kept?: CardKept
  /** The workflow's version tried on practice systems, as GET /api/v1/use-cases/{id}/simulation answers it. */
  readonly simulation?: UseCaseSimulationView
  /** The Jira projects the platform may use, as GET /api/v1/tools lists them. */
  readonly projects?: readonly string[]
  /** What the software finder answered for a name, as POST /api/v1/watchlist/find gives it. */
  readonly found?: { readonly name: string; readonly answer: FindOut }
}

const HELD: SetUp = { created: CREATED, at: Date.now() - 60_000, testRunId: null, testKey: 'k1', testAsked: null }

function render(node: ReactNode, { useCase = DRAFT, setUp = HELD, kept, unread = false, watched, made, run, simulation, projects, found }: World = {}): string {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  if (run) queryClient.setQueryData(keys.run(scope, run.run_id), run)
  if (unread) queryClient.getQueryCache().build(queryClient, { queryKey: keys.useCase(scope, useCase.use_case_id) }).setState({ status: 'error', error: new Error('no answer'), fetchStatus: 'idle' })
  else queryClient.setQueryData(keys.useCase(scope, useCase.use_case_id), useCase)
  if (setUp) queryClient.setQueryData(keys.setUp(scope, CREATED.use_case_id), setUp)
  if (watched) queryClient.setQueryData(keys.watchlist(scope), watched)
  if (projects) queryClient.setQueryData(keys.tools(), { tools: [], jira_projects: projects })
  if (found) queryClient.setQueryData(keys.softwareFind(scope, found.name), found.answer)
  if (made) queryClient.setQueryData(keys.made(scope, made.key), made.made)
  if (simulation) queryClient.setQueryData(keys.useCaseSimulation(scope, simulation.use_case_id), simulation)
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
  return render(<BuildingCard {...props} />, { setUp: { ...HELD, testRunId: test === null ? null : 'run_01JB8' }, ...world })
}

describe('the set-up card before Set up', () => {
  it('is a Draft that asks every open question in its own row and says Pick 1 more to finish in place of the main button', () => {
    const html = render(card(SETUP))
    expect(pill(html)).toBe('Draft')
    expect(html.match(/data-mark="ask"/g)).toHaveLength(1)
    expect(text(html)).toContain('Pick 1 more to finish')
    expect(buttons(html)).not.toContain('Turn on')
    expect(buttons(html).slice(-1)).toEqual(['Never mind'])
    expect(html, 'no button is shown dead').not.toMatch(/<button[^>]*disabled/)
  })

  it('marks a part the Planner filled in as I guessed, next to its Change', () => {
    const form = cardFrom(SETUP.name, SETUP.rows, TYPED, SETUP.parts)
    const guessed = { ...form, rows: form.rows.map((row) => (row.kind === 'look_for' ? { ...row, state: 'changed' as const, note: 'I picked the closed ones.' } : row)) }
    const html = render(<SetupCard start={{ form: guessed, plan: null, draftId: null, similar: null }} />)
    expect(text(html)).toContain('I guessed')
  })

  it('names the parts Watch, When and Then, in that order, and crosses each part it can’t do', () => {
    const html = render(card(setupCross as SetupCardReply, 'Every Friday at 5pm, sum up the tickets we closed this week in MOCK and colour them by team'))
    const keys = [...html.matchAll(/data-part="([^"]+)"/g)].map((m) => m[1])
    expect(keys).toEqual(['Watch', 'When', 'Then', 'cross-0'])
    expect(text(html)).toContain('Can’t do: “colour them by team” I didn’t follow this part.')
    expect(buttons(html)).toContain('Turn on')
  })

  it('is Dropped after Never mind, saying nothing was set up, with no button', () => {
    const html = render(card(SETUP), { kept: { form: cardFrom(SETUP.name, SETUP.rows, TYPED, SETUP.parts), draft: null, phase: { kind: 'dropped' } } })
    expect(pill(html)).toBe('Dropped')
    expect(text(html)).toContain('Nothing was set up.')
    expect(buttons(html)).toEqual([])
  })

  it('settles a card drawn again while it was being set up: built from what Set up made, or open with why it was refused', () => {
    const form = cardFrom(SETUP.name, SETUP.rows, TYPED, SETUP.parts)
    const built = render(card(SETUP), { kept: { form, draft: null, phase: { kind: 'creating', key: 'press_1' } }, made: { key: 'press_1', made: { kind: 'built', useCaseId: CREATED.use_case_id, draftKept: false, newAgents: [] } } })
    expect(pill(built)).not.toBe('Draft')
    expect(text(built)).not.toContain('Starting…')
    const refused = render(card(SETUP), { kept: { form, draft: null, phase: { kind: 'creating', key: 'press_2' } }, made: { key: 'press_2', made: { kind: 'refused', said: ['Give the workflow a name.'] } } })
    expect(pill(refused)).toBe('Draft')
    expect(text(refused)).toContain('Give the workflow a name.')
    expect(text(refused)).toMatch(/Pick \d more to finish/)
  })

  it('keeps their own words quoted for a clause it didn’t follow, as the sketch does', () => {
    const html = render(card(setupCross as SetupCardReply, 'Every Friday at 5pm, sum up the tickets we closed this week in MOCK and colour them by team'))
    expect(text(html)).toContain('Can’t do: “colour them by team” I didn’t follow this part.')
  })

  it('leads with the workflow they already have when the name matches one', () => {
    const html = render(card(setupCard as SetupCardReply), { useCase: { ...ON, use_case_id: 'uc_01JB8', name: 'Weekly summary of closed tickets', schedule: { ...DRAFT.schedule!, day: 'friday', at: '17:00' } } })
    expect(text(html)).toContain('It already watches langchain-ai/langgraph, every Friday at 17:00.')
    expect(buttons(html)).toEqual(['Set up another', 'Open it'])
  })
})

describe('the Jira step of the set-up card', () => {
  const TICKET = 'Check LangGraph on GitHub for new releases every weekday at 9am, and create a Jira ticket when there’s a new one.'
  const ROWS: SetupCardReply['rows'] = [
    { kind: 'schedule', text: 'Every weekday at 9am', state: 'understood', note: null },
    { kind: 'look_for', text: 'New releases of langchain-ai/langgraph', state: 'understood', note: null },
    { kind: 'do', text: 'Create a Jira ticket for each new one', state: 'understood', note: null },
    { kind: 'where', text: '', state: 'missing', note: null },
  ]
  const reply: SetupCardReply = { ...SETUP, rows: ROWS, parts: [] }
  const partText = (html: string, key: string) =>
    text(
      (html.split(`data-part="${key}"`)[1] ?? '')
        .split('data-part=')[0]
        ?.replace(/^[^>]*>/, '')
        .replace(/<[^>]*$/, '') ?? '',
    )

  it('asks which project in the Then row, with the platform’s projects as buttons and a link to type another', () => {
    const html = render(card(reply, TICKET), { projects: ['MOCK'] })
    const then = partText(html, 'Then')
    expect(then).toContain('Create 1 Jira ticket in which project?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['MOCK', 'Another project']))
    expect(html.match(/data-mark="ask"/g), 'the Then row is the one open part').toHaveLength(1)
    expect(then, 'no empty chip for where it goes').not.toContain('where it goes')
    expect(then).not.toContain('Where should the result go?')
    expect(html, 'no free-text box until Another project').not.toMatch(/<input[^>]*type="text"/)
    expect(text(html)).toContain('Pick 1 more to finish')
  })

  it('says each ticket waits for an Approver’s yes in Teams under the project question, in place of After a yes', () => {
    const html = render(card(reply, TICKET), { projects: ['MOCK'] })
    expect(text(html)).not.toContain('After a yes')
    expect(partText(html, 'Then')).toContain('Each ticket waits for an Approver’s yes in Teams.')
  })

  it('keeps the same sentence once Set up is pressed', () => {
    const form = cardFrom(reply.name, ROWS, TICKET, [])
    const words = text(renderToStaticMarkup(<PartsList parts={frozenParts(form, null, null, null)} />))
    expect(words).toContain('Each ticket waits for an Approver’s yes in Teams.')
    expect(words).not.toContain('After a yes')
  })

  it('asks every open part at once from the start: How often?, At what time? and the project, each with its buttons, and counts them', () => {
    const open: SetupCardReply = { ...reply, rows: ROWS.map((row) => (row.kind === 'schedule' ? { ...row, text: '', state: 'missing' as const } : row)) }
    const html = render(card(open, 'Check LangGraph and create a Jira ticket'), { projects: ['MOCK'] })
    expect(html.match(/data-mark="ask"/g), 'When and Then are both open').toHaveLength(2)
    const when = partText(html, 'When')
    expect(when).toContain('How often?')
    expect(when).toContain('At what time?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Every day', 'Every weekday', 'Every week', 'Only when I run it', '8:00', '9:00', '13:00', '17:00', 'Another time', 'MOCK', 'Another project']))
    expect(text(html)).toContain('Pick 2 more to finish')
    expect(buttons(html), 'Turn on waits until nothing is left').not.toContain('Turn on')
  })

  it('shows no dead button, and the project buttons are a group named by the question', () => {
    const html = render(card(reply, TICKET), { projects: ['MOCK'] })
    expect(html).not.toMatch(/<button[^>]*disabled/)
    expect(html).toMatch(/role="group" aria-labelledby="[^"]+"/)
  })

  it('opens the key box at once when the platform lists no project', () => {
    const html = render(card(reply, TICKET), { projects: [] })
    expect(html).toMatch(/<input[^>]*type="text"/)
    expect(buttons(html)).not.toContain('Another project')
  })
})

describe('the repository row of the set-up card', () => {
  const ROWS: SetupCardReply['rows'] = [
    { kind: 'schedule', text: 'Every weekday at 9am', state: 'understood', note: null },
    { kind: 'look_for', text: 'New releases of FastAPI', state: 'understood', note: null },
    { kind: 'do', text: 'Tell me here', state: 'understood', note: null },
    { kind: 'where', text: 'Here in the chat', state: 'understood', note: null },
  ]
  const reply: SetupCardReply = { ...SETUP, rows: ROWS, parts: [] }
  const TYPED_WORDS = 'Every weekday at 9am, check FastAPI for new releases'
  const match = (repo: string, what: string) => ({ kind: 'github' as const, repo, what, why: 'On the reviewed list.', releases: 'published' as const, newest: '0.121.0', already_listed: null })
  const partText = (html: string) => text((html.split('data-part="Watch"')[1] ?? '').split('data-part=')[0]?.replace(/^[^>]*>/, '').replace(/<[^>]*$/, '') ?? '')

  it('fills the repository with the one clear match, with a tick, Change and where it was found', () => {
    const html = render(card(reply, TYPED_WORDS), { found: { name: 'FastAPI', answer: { status: 'found', matches: [match('fastapi/fastapi', 'FastAPI web framework')] } } })
    const watch = partText(html)
    expect(watch).toContain('fastapi/fastapi')
    expect(watch).toContain('Found on GitHub')
    expect(buttons(html)).toContain('Change')
    expect(html.match(/data-mark="ask"/g)).toBeNull()
  })

  it('shows several matches as buttons with what each is, and Another repository', () => {
    const html = render(card(reply, TYPED_WORDS), { found: { name: 'FastAPI', answer: { status: 'found', matches: [match('fastapi/fastapi', 'FastAPI web framework'), match('tiangolo/fastapi', 'An older address')] } } })
    expect(partText(html)).toContain('Which repository should I watch?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['fastapi/fastapi FastAPI web framework', 'tiangolo/fastapi An older address', 'Another repository']))
    expect(text(html)).toContain('Pick 1 more to finish')
  })

  it('shows only Another repository, with its hint, when the finder knows none', () => {
    const html = render(card(reply, TYPED_WORDS), { found: { name: 'FastAPI', answer: { status: 'not_known', message: 'I don’t know it.' } } })
    expect(partText(html)).toContain('The public repository to watch, as owner/name.')
    expect(html).toMatch(/<input[^>]*type="text"/)
    expect(buttons(html)).not.toContain('Another repository')
  })

  it('says it is looking while the finder works, and counts the row as open', () => {
    const html = render(card(reply, TYPED_WORDS))
    expect(partText(html)).toContain('Looking for the repository')
    expect(text(html)).toContain('Pick 1 more to finish')
  })
})

describe('a workflow that runs only when someone presses Run now', () => {
  const TYPED_BY_HAND = 'On demand, sum up the tickets we closed this week'
  const BY_HAND: SetupCardReply = { ...SETUP, rows: SETUP.rows.map((row) => (row.kind === 'schedule' ? { ...row, text: 'On demand' } : row)) }
  const partText = (html: string, key: string) =>
    text(
      (html.split(`data-part="${key}"`)[1] ?? '')
        .split('data-part=')[0]
        ?.replace(/^[^>]*>/, '')
        .replace(/<[^>]*$/, '') ?? '',
    )

  it('says Only when I run it under When, with no time zone and no time to ask', () => {
    const html = render(card(BY_HAND, TYPED_BY_HAND))
    expect(partText(html, 'When')).toContain('Only when I run it')
    expect(partText(html, 'When')).not.toMatch(/Singapore|SGT|at what time/)
  })

  it('keeps Only when I run it under When once Turn on is pressed', () => {
    const form = cardFrom(BY_HAND.name, BY_HAND.rows, TYPED_BY_HAND, BY_HAND.parts)
    const html = render(<PartsList parts={frozenParts(form, null, null, null)} />)
    expect(partText(html, 'When')).toBe('Will do: When Only when I run it')
  })

  it('says On, and that it runs only when you press Run now, once it is on', () => {
    const html = building(passed, { useCase: { ...ON, schedule: null, next_run_at: null } })
    expect(pill(html)).toBe('On')
    expect(text(html)).toContain('On. Runs only when you press Run now.')
  })
})

describe('what the card knows about the software it watches', () => {
  const plan = { task: 'Check it', answer: planUseOne as PlanOut }
  const reply: SetupCardReply = { ...SETUP, rows: [{ kind: 'look_for', text: 'New releases of langchain-ai/langgraph', state: 'understood', note: null }, ...SETUP.rows.filter((row) => row.kind !== 'look_for')] }
  const form = cardFrom(reply.name, reply.rows, TYPED, reply.parts)

  it('says the version they run under Watch, from the watchlist, when the software is on it', () => {
    const html = render(<SetupCard start={{ form, plan: { ...plan, task: taskWithoutSchedule(form.rows) }, draftId: null, similar: null }} />, { watched: statuses as WatchlistView })
    expect(text(html)).toContain('You run 1.2.14')
  })

  it('names the repository once after Set up, not again as a value', () => {
    const html = renderToStaticMarkup(<PartsList parts={frozenParts(form, planView(planUseOne as PlanOut, form.rows), true, null)} short />)
    expect(text(html)).toContain('New releases of langchain-ai/langgraph')
    expect(text(html)).not.toContain('GitHub repository: langchain-ai/langgraph')
  })
})

describe('the set-up card after Set up', () => {
  it('shows nothing of the line before the build log says the blocks were added', () => {
    const html = building(null, { setUp: { ...HELD, at: Date.now() + 60_000 } })
    expect(pill(html)).toBe('Building')
    expect(text(html)).toContain('Starting…')
    expect(html.match(/<li[^>]*data-off="true"/g)?.length, 'each of the four steps waits').toBe(4)
  })

  it('shows the line and the safety checker’s note once the log has replayed, and claims no test run before the platform names one', () => {
    const html = building(null)
    expect(pill(html)).toBe('Building')
    expect(html).not.toContain('data-off')
    expect(text(html)).toContain('I added an approval step. Before each ticket is made, an Approver must say yes in Teams.')
    expect(text(html)).toContain('Saved as a draft in n8n.')
    expect(text(html)).not.toContain('Test run…')
    expect(html, 'the yes the safety checker added is ringed').toContain('data-added="true"')
    expect(buttons(html)).toEqual([])
  })

  it('says it can’t read the workflow, with Try again, and starts no test run while it doesn’t know it is a draft', () => {
    const html = building(null, { unread: true })
    expect(text(html)).toContain('I couldn’t read the workflow just now, so the test run waits.')
    expect(buttons(html)).toEqual(['Try again'])
  })

  it('follows the test run’s own events while it works, with no button to press', () => {
    const html = building(working)
    expect(text(html)).toContain('Test run…')
    expect(html).toContain('data-state="now"')
    expect(buttons(html)).toEqual([])
  })

  it('is Ready once the test run passed up to the yes, says nothing was written, and turns itself on', () => {
    const html = building(passed)
    expect(pill(html)).toBe('Ready')
    expect(text(html)).toContain('Test run passed up to the yes. Nothing was written.')
    expect(buttons(html), 'it turns itself on, so there is no Turn it on to press').toEqual([])
    expect(text(html), 'the write was never made').toContain('Nothing written')
  })

  it('says why it could not turn on, with Try again, when the test passed but turning on failed', () => {
    const html = building(passed, {}, { problem: 'Could not turn it on. The platform is busy.' })
    expect(text(html)).toContain('Could not turn it on. The platform is busy.')
    expect(buttons(html)).toEqual(['Try again'])
  })

  it('stays a Draft when the test run stopped, with one reason and one button', () => {
    const html = building(stopped, { run: { ...(failedView as RunView), run_id: 'run_01JB8' } })
    expect(pill(html)).toBe('Draft')
    expect(text(html)).toContain("The test run stopped. GitHub didn't answer. Nothing was written. It stays a Draft.")
    expect(buttons(html), 'a failure Try again cannot fix is never a dead end').toEqual(['Try again', 'Open the workflow'])
  })

  it('says why its own test run stopped, never the reason of another run the workflow had', () => {
    const older = { at: '2026-11-03T02:14:13Z', what_happened: "Jira is not connected, so an agent couldn't read it." }
    const lastRun: UseCaseView['last_run'] = { run_id: 'run_older', state: 'failed', at: '2026-11-03T02:13:00Z', test: true, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: false, you_can_decide: false, you_can_open: false, retryable: false, reason: 'AgentError', stop: older }
    const own = building(stopped, { useCase: { ...DRAFT, last_run: lastRun }, run: { ...(failedView as RunView), run_id: 'run_01JB8' } })
    expect(text(own)).toContain("The test run stopped. GitHub didn't answer.")
    expect(text(own)).not.toContain('Jira is not connected')
    const unread = building(stopped, { useCase: { ...DRAFT, last_run: lastRun } })
    expect(text(unread), 'until its own run is read, only that it stopped').toContain('The test run stopped.')
    expect(text(unread)).not.toContain('Jira is not connected')
  })

  it('says Try again when the platform would not start the test run', () => {
    const html = building(null, {}, { problem: 'Could not start the test run. The platform is busy.' })
    expect(text(html)).toContain('Could not start the test run.')
    expect(buttons(html)).toEqual(['Try again'])
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
    expect(text(html)).toMatch(/On\. First run (today|tomorrow|[A-Z][a-z]+day|[A-Z][a-z]{2} \d+ [A-Z][a-z]{2}), 8:00\./)
    expect(buttons(html)).toEqual([])
  })
})

describe('the set-up card tried on practice systems (ADR 0054)', () => {
  const DONE = (simulated as DraftedWorkflowView).simulation as SimulationView
  const tried = (simulation: SimulationView | null): UseCaseSimulationView => ({ use_case_id: CREATED.use_case_id, version: 1, simulation })
  const STILL_TESTS = 'Turn on still runs the real test, which writes nothing.'

  it('leads with the result as the drafted card does, code’s grade first, and never stands in for the test run', () => {
    const words = text(building(null, { simulation: tried(DONE) }))
    expect(words).toContain('Tried 5 cases on practice systems: 4 passed.')
    expect(words.indexOf('Failed Source not found')).toBeLessThan(words.indexOf('Passed Happy path'))
    expect(words).toContain('A failed case doesn’t stop Turn on. You decide.')
    expect(words).toContain(STILL_TESTS)
  })

  it('says so while it is being tried, with each case’s limit, and claims no result', () => {
    const running: SimulationView = { ...DONE, state: 'running', tried: 0, passed: 0, cases: [] }
    const words = text(building(null, { simulation: tried(running) }))
    expect(words).toContain('Trying it on practice systems. Each case can take up to 2 minutes.')
    expect(words).not.toContain('passed')
  })

  it('offers Try again only to whoever can start it, never a dead button', () => {
    const notRun: SimulationView = { ...DONE, state: 'not_run', tried: 0, passed: 0, cases: [], said: 'The practice systems didn’t answer, so nothing was tried.', can_try_again: true }
    expect(buttons(building(null, { simulation: tried(notRun) }))).toContain('Try again')
    const bob = building(null, { simulation: tried({ ...notRun, can_try_again: false }) })
    expect(text(bob)).toContain('The practice systems didn’t answer, so nothing was tried.')
    expect(buttons(bob)).not.toContain('Try again')
  })

  it('says nothing of practice systems for a workflow with nothing to try', () => {
    expect(text(building(null, { simulation: tried(null) }))).not.toContain('practice systems')
  })
})

describe('Building in n8n', () => {
  it('draws the blocks, says what the builder did and lists the checks, with the footnote that holds today', () => {
    const html = render(<BuildPanel id={CREATED.use_case_id} />)
    expect(text(html)).toContain('Building in n8n')
    expect(text(html)).toContain('Saved as a draft in n8n.')
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
    const html = text(render(<BuildPanel id={CREATED.use_case_id} />, { setUp: { ...HELD, created: shared, at: 0 } }))
    expect(html).not.toContain('n8n')
  })
})
