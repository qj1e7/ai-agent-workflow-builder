import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import leftOutUseCase from '../../../../contracts/fixtures/cards/use-case.left-out.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import troubleshooting from '../../../../contracts/fixtures/troubleshooting/failure.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import peopleList from '../../../../contracts/fixtures/people/list.json'
import versionedUseCase from '../../../../contracts/fixtures/builder/use-case.versioned.json'
import openInN8n from '../../../../contracts/fixtures/builder/use-case.open-in-n8n.json'
import undoneUseCase from '../../../../contracts/fixtures/builder/use-case.undone.json'
import changed from '../../../../contracts/fixtures/builder/versions.json'
import undone from '../../../../contracts/fixtures/builder/versions.undone.json'
import simulated from '../../../../contracts/fixtures/builder/drafted.simulated.json'
import { App } from '../../App'
import { ApiError, type ApiClient } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { DraftedWorkflowView, Me, PersonOut, RunView, SimulationView, TroubleshootingOut, UseCaseSimulationView, UseCaseView, VersionView, WatchlistView } from '../../api/types'
import { keys } from '../../api/queries'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import type { LastRun } from './workflow'
import { formatterFactory } from './workflow'
import { saveScheduleOptions } from '../../api/workflowQueries'
import { WhenEditor } from './When'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob', 'carol'].includes(person.id))

const AGENTS = agentUseCase as UseCaseView
const ALICE_LEFT = 'Not running: Alice is no longer on the People list. An Operator can take it over by saving the schedule.'
const ALICE_NOT_AN_OPERATOR = 'Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.'
const CAROL_LEFT = 'Not running: Carol is no longer on the People list. An Operator can take it over by saving the schedule.'
const WATCHLIST = watchlistUseCase as UseCaseView
const NOW = new Date('2026-11-04T15:00:00+08:00')

const STOPPED: LastRun = { run_id: 'run_01JB9', state: 'failed', at: '2026-11-04T02:14:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: false, you_can_decide: false, you_can_open: true, retryable: false, reason: 'AgentError', stop: { at: '2026-11-04T02:14:00Z', what_happened: 'An agent could not finish its work.' } }

interface Setup {
  /** The workflow's last run as the platform answers it, changed from a stopped run. */
  readonly last?: Partial<LastRun>
  readonly me?: Me
  readonly useCase?: UseCaseView | Error
  readonly runs?: RunView[]
  readonly id?: string
  readonly advice?: TroubleshootingOut
  /** The versions the platform lists for the workflow at its version. */
  readonly versions?: VersionView[]
  /** The watchlist as the platform answers it, for the watchlist's own page. */
  readonly watchlist?: WatchlistView
  readonly path?: string | undefined
  /** Its version tried on practice systems, as GET /api/v1/use-cases/{id}/simulation answers it. */
  readonly simulation?: SimulationView | null
}

function render({ me = ALICE, useCase: given = AGENTS, runs = [], id, advice, last, versions, watchlist, path, simulation }: Setup = {}): string {
  const useCase = last && !(given instanceof Error) ? { ...given, last_run: { ...STOPPED, ...last } } : given
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const useCaseId = id ?? (useCase instanceof Error ? 'uc_gone' : useCase.use_case_id)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['people', scope], TEAM)
  queryClient.setQueryData(['runs', scope], runs)
  if (watchlist) queryClient.setQueryData(['watchlist', scope], watchlist)
  const stopped = runs.find((run) => run.use_case_id === useCaseId && run.state === 'failed')
  if (advice && stopped?.state === 'failed') queryClient.setQueryData(['troubleshoot', scope, stopped.run_id, stopped.last_seq], advice)
  const key = ['use-case', scope, useCaseId]
  if (useCase instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: useCase, fetchStatus: 'idle' })
  else queryClient.setQueryData(key, useCase)
  if (versions && !(useCase instanceof Error)) queryClient.setQueryData(['versions', scope, useCaseId, useCase.version], versions)
  if (simulation !== undefined && !(useCase instanceof Error)) {
    const tried: UseCaseSimulationView = { use_case_id: useCaseId, version: useCase.version, simulation }
    queryClient.setQueryData(keys.useCaseSimulation(scope, useCaseId), tried)
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path ?? `/workflows/${useCaseId}`]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

function renderEditor(schedule: UseCaseView['schedule']): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <WhenEditor schedule={schedule} version={1} isPending={false} save={() => undefined} onDone={() => undefined} />
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const buttons = (html: string) => [...mainOf(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const sectionText = (html: string, heading: string) => text(new RegExp(`<h2[^>]*>${heading}</h2>([\\s\\S]*?)</section>`).exec(mainOf(html))?.[1] ?? '')

/** The When section's words, without who set it and without the next run, and without the Change button. */
const whenOf = (html: string) =>
  sectionText(html, 'When')
    .replace(/ Next run: .*$/, '')
    .replace(/ Not running: .*$/, '')
    .replace(/ Set by \w+\.$/, '')
    .replace(/ (Change|Set) when it runs/, '')
/** The next run, the third fact of the strip under the sentence. */
const nextOf = (html: string) => sectionText(html, 'Next run')
const sentenceOfHtml = (html: string) => text(/<p class="[^"]*sentence[^"]*">([\s\S]*?)<\/p>/.exec(mainOf(html))?.[1] ?? '')

describe('a workflow page', () => {
  it('shows the kind line, its name, and whether it is on', () => {
    const html = render()
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe('LangGraph release check')
    expect(text(mainOf(html))).toContain('Workflow LangGraph release check')
    expect(mainOf(html)).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
  })

  it('says why a workflow that could not move to n8n starts no run, and never gives a next run', () => {
    const refused = 'Not running. n8n did not take it yet, so it can\'t run on its schedule. The platform tries again every minute. If this stays, ask for help.'
    const schedule = { day: 'tuesday', at: '07:30', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } as const
    const html = text(mainOf(render({ useCase: { ...AGENTS, schedule, next_run_at: null, move_refused: refused } })))
    expect(html).toContain(refused)
    expect(html).not.toContain('Not scheduled')
    expect(html).not.toMatch(/Next run (Mon|Tue|Wed|Thu|Fri|Sat|Sun)/)
  })

  it('says it moves to its own n8n workflow after the run that holds it back, and only then', () => {
    expect(text(mainOf(render({ useCase: { ...AGENTS, moving_to_n8n: true } })))).toContain('Moving to n8n after this run.')
    expect(text(mainOf(render()))).not.toContain('Moving to n8n')
  })

  it('says what it does in one sentence built from what the platform stored, never a guessed time', () => {
    expect(sentenceOfHtml(render())).toBe('Check langchain-ai/langgraph on GitHub for a new release when an Operator presses Run now. If there is one, create an upgrade ticket in Jira project MOCK, after approval.')
    const html = render({ useCase: { ...AGENTS, next_run_at: '2026-11-05T00:00:00Z', schedule: { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(sentenceOfHtml(html)).toBe('Every day at 8:00, check langchain-ai/langgraph on GitHub for a new release. If there is one, create an upgrade ticket in Jira project MOCK, after approval.')
  })

  it('draws its steps as the run line, large, with a tag under each', () => {
    const line = text(/<div[^>]*class="[^"]*large[^"]*"[\s\S]*?<\/ol>/.exec(mainOf(render()))?.[0] ?? '')
    expect(line).toContain('Run now No system access')
    expect(line).toContain('Check release Reads only')
    expect(line).toContain('Ask for approval Waits for approval')
    expect(line).toContain('Create Jira tickets Writes after approval')
  })

  it('keeps what it was set up without as a Left out line, and none when nothing was left out', () => {
    const line = 'Left out: “colour them by team”. It was set up without that part.'
    expect(text(mainOf(render({ useCase: leftOutUseCase as UseCaseView })))).toContain(line)
    expect(text(mainOf(render()))).not.toContain('Left out')
  })

  it('says when it runs, when it runs next, and who says yes', () => {
    const html = render()
    expect(whenOf(html)).toBe('Runs only when you press Run now.')
    expect(mainOf(html), 'a workflow with no schedule has no next run to give').not.toContain('>Next run</h2>')
    expect(sectionText(html, 'Who approves')).toBe('Any Approver but you, in Teams. Nothing is written until an Approver approves it. Who can’t approve Nobody approves their own work. The workflow’s owner, whoever starts a run and whoever retries it can’t approve that run.')
  })

  it('keeps the sketch’s short Who says yes line, with the whole own-work rule folded one tap away', () => {
    const rule = /<details[^>]*>\s*<summary>Who can’t approve<\/summary>([\s\S]*?)<\/details>/.exec(mainOf(render({ useCase: SCHEDULED })))
    expect(text(rule?.[1] ?? '')).toBe('Nobody approves their own work. The workflow’s owner, whoever starts a run and whoever retries it can’t approve that run. A scheduled run starts as Carol.')
    expect(rule?.[0]).not.toMatch(/<details[^>]*\bopen\b/)
  })

  it('gives its schedule’s day and time, and its next run', () => {
    const html = render({ useCase: { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(whenOf(html)).toBe('Every Monday at 9:00 Singapore time (SGT). Set by Alice.'.replace(' Set by Alice.', ''))
    expect(nextOf(html)).toBe('Mon 9 Nov, 9:00')
  })

  it('for a London schedule, gives the next run in London time and says so, under When and in Recent runs', () => {
    const london: UseCaseView = { ...AGENTS, next_run_at: '2026-11-04T09:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' } }
    const html = render({ useCase: london })
    expect(whenOf(html)).toBe('Every day at 9:00 London time.')
    expect(nextOf(html)).toBe('Today, 9:00 London time')
    expect(text(mainOf(html))).toContain('No runs yet First run Today, 9:00 London time.')
  })

  it('for a London schedule, keeps each run’s start in Singapore time, as every time without a zone named is', () => {
    const london: UseCaseView = { ...AGENTS, next_run_at: '2026-11-04T09:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' } }
    const ran = { ...(done as RunView), use_case_id: london.use_case_id, started_at: '2026-11-03T09:00:00Z' }
    const html = render({ useCase: london, runs: [ran] })
    expect(nextOf(html)).toBe('Today, 9:00 London time')
    expect(text(mainOf(html))).toContain('Tue 3 Nov, 17:00 1 ticket created, approved by Bob Done')
  })

  it('for a zone the browser cannot read, names it from its id and gives the next run in Singapore time, saying so', () => {
    const build = formatterFactory.build
    const spy = vi.spyOn(formatterFactory, 'build').mockImplementation((zone) => {
      if (zone === 'Europe/Kyiv') throw new RangeError(`Invalid time zone specified: ${zone}`)
      return build(zone)
    })
    try {
      const html = render({ useCase: { ...AGENTS, next_run_at: '2026-11-04T07:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/Kyiv', owner_name: 'Alice' } } })
      expect(whenOf(html)).toBe('Every day at 9:00 Kyiv time.')
      expect(nextOf(html)).toBe('Today, 15:00 Singapore time')
      expect(text(mainOf(html))).toContain('First run Today, 15:00 Singapore time.')
    } finally {
      spy.mockRestore()
    }
  })

  it('while paused, keeps its schedule under When and says Paused only for the next run', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused', next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(whenOf(html)).toBe('Every Monday at 9:00 Singapore time (SGT).')
    expect(nextOf(html)).toBe('Paused')
  })

  it('while its schedule is held, keeps the schedule in the Schedule row and says for the next run why it is not running', () => {
    const removed = render({ useCase: { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_removed', held_words: ALICE_LEFT } } })
    const notOperator = render({
      useCase: { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_not_an_operator', held_words: ALICE_NOT_AN_OPERATOR } },
    })
    expect(whenOf(removed)).toBe('Every Monday at 9:00 Singapore time (SGT).')
    expect(nextOf(removed)).toBe('Not running: Alice is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(nextOf(notOperator)).toBe('Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.')
  })

  it('while paused and held, says Paused only, as the Software page does', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused', next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_removed' } } })
    expect(nextOf(html)).toBe('Paused')
    expect(text(mainOf(html))).not.toContain('Not running')
  })

  it('gives an Operator Pause and a More actions button, last on the page, and keeps Run now and Delete inside the closed menu', () => {
    const html = render({ useCase: SCHEDULED })
    expect(buttons(html)).toEqual(expect.arrayContaining(['Pause', 'More actions']))
    expect(buttons(html)).not.toContain('Run now')
    expect(buttons(html)).not.toContain('Delete')
    expect(mainOf(html)).toMatch(/<button[^>]*aria-haspopup="menu"[^>]*aria-expanded="false"[^>]*>More actions/)
  })

  it('gives an Operator a Change button, a link to the Home chat with this workflow’s card, before More actions and never the one primary action', () => {
    const html = render({ useCase: SCHEDULED })
    const link = new RegExp(`<a\\b[^>]*href="/\\?change=${SCHEDULED.use_case_id}"[^>]*>([\\s\\S]*?)</a>`).exec(mainOf(html))
    expect(text(link?.[1] ?? '')).toBe('Change')
    expect(link?.[0]).not.toMatch(/_primary_/)
    expect(mainOf(html).indexOf('href="/?change=')).toBeLessThan(mainOf(html).indexOf('More actions'))
  })

  it('offers no Change to an Approver, or for the Software watchlist, which has its own page for its schedule', () => {
    expect(mainOf(render({ me: BOB, useCase: SCHEDULED }))).not.toContain('?change=')
    expect(mainOf(render({ useCase: WATCHLIST }))).not.toContain('?change=')
  })

  it('makes Run now the one main button of a workflow with no schedule, first in the row, with Delete still last in the closed menu', () => {
    const html = render()
    const row = buttons(html).filter((label) => ['Run now', 'Pause', 'More actions'].includes(label))
    expect(row, 'Run now leads, More actions is last').toEqual(['Run now', 'Pause', 'More actions'])
    expect(buttons(html)).not.toContain('Delete')
    expect(mainOf(html)).toMatch(/<button[^>]*class="[^"]*_primary_[^"]*"[^>]*>(<svg[\s\S]*?<\/svg>)?Run now<\/button>/)
    expect(mainOf(html).match(/_primary_/g), 'one primary action for the state').toHaveLength(1)
  })

  it('keeps Run now quiet when the banner already holds the state’s main action', () => {
    const html = render({ last: { state: 'awaiting_approval', reason: null, stop: null, you_can_decide: true } })
    expect(buttons(html)).toContain('Run now')
    expect(mainOf(html).match(/_primary_/g), 'Review and decide is the one primary action').toHaveLength(1)
    expect(mainOf(html)).toMatch(/_primary_[^>]*>Review and decide/)
  })

  it('orders the page as the sketch does: the title row, the sentence, When, Who approves, Next run, the line, then Recent runs, with no banner and no Agents section', () => {
    const html = mainOf(render({ runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }], useCase: { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: null } } }))
    const at = (needle: string) => html.indexOf(needle)
    const order = [at('<h1'), at('>Pause<'), at('sentence'), at('>When</h2>'), at('>Who approves</h2>'), at('>Next run</h2>'), at('Check release'), at('>Recent runs</h2>')]
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(html).not.toContain('Agents')
    expect(html).not.toMatch(/class="[^"]*_banner_/)
  })

  const SCHEDULED: UseCaseView = { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: null } }

  it('puts the change beside When, as Change, or Set when there is none', () => {
    expect(buttons(render({ useCase: SCHEDULED }))).toContain('Change when it runs')
    expect(buttons(render())).toContain('Set when it runs')
  })

  it('says under When who set the schedule', () => {
    expect(sectionText(render({ useCase: SCHEDULED }), 'When')).toContain('Set by Carol.')
  })

  it('says a schedule nobody saved here was set in n8n, and offers no change to one made in n8n', () => {
    const inN8n = { ...SCHEDULED, schedule: { ...SCHEDULED.schedule!, owner_name: null } }
    expect(sectionText(render({ useCase: inN8n }), 'When')).toContain('Set in n8n.')
    expect(sectionText(render({ useCase: inN8n }), 'When')).not.toContain('null')
    expect(buttons(render({ useCase: { ...inN8n, made_in_n8n_by: 'carol' } }))).not.toContain('Change when it runs')
  })

  it('shows an Approver who is not an Operator neither control', () => {
    for (const useCase of [SCHEDULED, AGENTS]) expect(buttons(render({ me: BOB, useCase })).filter((label) => /when it runs/i.test(label))).toEqual([])
  })

  it('opens the editor in place of the row: a day, a time, Save and Cancel, and says the runs then count as the Operator’s work', () => {
    const html = renderEditor(SCHEDULED.schedule)
    expect(html).toContain('<option value="every_day">Every day</option>')
    expect(html).toContain('<option value="monday" selected="">Every Monday</option>')
    expect(html).toContain('type="time"')
    expect(text(html)).toContain('Save Cancel')
    expect(text(html)).toContain('Saving makes you the owner of this schedule. Its runs then count as your work, so you won’t be able to approve them.')
  })

  it('opens with no time chosen while the workflow has no schedule, so a time is never guessed', () => {
    expect(renderEditor(null)).toMatch(/<input[^>]*type="time"[^>]*value=""/)
    expect(renderEditor(SCHEDULED.schedule)).toContain('value="09:00"')
  })

  it('tells everyone a held schedule can be taken over by saving it', () => {
    const held: UseCaseView = { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: 'owner_removed', held_words: CAROL_LEFT } }
    for (const me of [ALICE, BOB]) {
      expect(nextOf(render({ me, useCase: held }))).toContain('An Operator can take it over by saving the schedule.')
    }
  })

  it('lets an Operator take a held schedule over from When: Change opens on it, the save carries the version read, and the saved view names them and its next run', async () => {
    const held: UseCaseView = { ...AGENTS, version: 3, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: 'owner_removed', held_words: CAROL_LEFT } }
    expect(buttons(render({ me: ALICE, useCase: held }))).toContain('Change when it runs')
    expect(buttons(render({ me: BOB, useCase: held })).filter((label) => /when it runs/i.test(label)), 'only an Operator can take it over').toEqual([])
    const taken: UseCaseView = { ...held, next_run_at: '2026-11-09T01:00:00Z', schedule: { ...held.schedule!, owner_name: 'Alice', held: null, held_words: null } }
    const sent: unknown[] = []
    const client = { PUT: (path: string, init: unknown) => (sent.push([path, init]), Promise.resolve({ data: taken, response: { ok: true, status: 200 } })) } as unknown as ApiClient

    await saveScheduleOptions(client, new QueryClient(), 'me', held.use_case_id).mutationFn({ day: 'monday', at: '09:00', expected_version: 3 })

    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/schedule', { params: { path: { use_case_id: held.use_case_id } }, body: { day: 'monday', at: '09:00', expected_version: 3, via: 'page' } }]])
    const after = render({ me: ALICE, useCase: taken })
    expect(sectionText(after, 'When')).toContain('Set by Alice.')
    expect(nextOf(after)).not.toContain('Not running')
  })

  it('gives an Approver who may approve and the recent runs, but no manage buttons', () => {
    const html = render({ me: BOB, runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(sectionText(html, 'Who approves')).toMatch(/^Any Approver but Alice, in Teams\. Nothing is written until an Approver approves it\. Who can’t approve /)
    expect(text(mainOf(html))).toContain('Recent runs')
    expect(mainOf(html)).toContain('href="/runs/run_01JB8"')
    expect(buttons(html).filter((label) => /Run now|Pause|Resume|Delete|More actions/.test(label))).toEqual([])
  })

  it('is read only for an Approver, paused or not: one note names the Operators, and nothing is dead', () => {
    for (const state of ['on', 'paused'] as const) {
      const html = render({ me: BOB, useCase: { ...AGENTS, state }, last: {} })
      const main = text(mainOf(html))
      expect(main.match(/Only Operators change/g)).toHaveLength(1)
      expect(main).toContain('Only Operators change this workflow. Ask Alice or Carol.')
      expect(mainOf(html)).not.toMatch(/disabled=""|aria-disabled="true"/)
      expect(buttons(html).filter((label) => /Run now|Pause|Resume|Delete|More actions|Change|Set when|Turn/.test(label))).toEqual([])
    }
    expect(text(mainOf(render()))).not.toContain('Only Operators change')
  })

  it('while paused, offers Resume instead of Pause and Run now, and its next run reads Paused', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused' } })
    expect(buttons(html)).toContain('Resume')
    expect(buttons(html)).not.toContain('Pause')
    expect(buttons(html)).not.toContain('Run now')
    expect(nextOf(html)).toBe('Paused')
    expect(mainOf(html)).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
  })

  it('opens the run from the title row for someone who may not decide a waiting run, and decides for someone who may', () => {
    const waiting = { last: { state: 'awaiting_approval' as const, proposed: 1, tickets: true, you_can_decide: false, reason: null } }
    expect(mainOf(render({ ...waiting }))).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
    expect(mainOf(render({ me: BOB, useCase: AGENTS, last: { ...waiting.last, you_can_decide: true } }))).toMatch(/<a[^>]*>Review and decide<\/a>/)
  })

  it('shows a stopped last run, linking to it', () => {
    const html = render({ last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }, { ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(mainOf(html)).toMatch(/data-tone="bad"[^>]*>.*Stopped<\/span>/)
    const first = /<li[^>]*data-run-id="([^"]+)"[^>]*data-state="([^"]+)"/.exec(html)
    expect([first?.[1], first?.[2]]).toEqual(['run_01JB9', 'failed'])
  })

  const recentOf = (html: string) => text(/<section[^>]*aria-labelledby[^>]*>\s*<h2[^>]*>Recent runs<\/h2>([\s\S]*?)<\/section>/.exec(mainOf(html))?.[0] ?? '')
  const noBanner = (html: string) => expect(mainOf(html), 'the state is said by the pill, the title row and Recent runs, not a banner as well').not.toMatch(/class="[^"]*_banner_/)

  it('for a stop, retryable or not, the one action is Open the run in the title row, as in the sketch, with no banner', () => {
    for (const retryable of [true, false]) {
      const html = render({ last: { retryable } })
      noBanner(html)
      expect(mainOf(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
      expect(text(mainOf(html))).not.toMatch(/Retry the run|See why it stopped/)
    }
  })

  it('for a run n8n lost, keeps the pill On, says Lost in Recent runs, and opens the run from the title row', () => {
    const html = render({ last: { state: 'lost', reason: null }, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0', state: 'lost' } as RunView] })
    expect(mainOf(html)).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
    expect(mainOf(html)).not.toMatch(/Needs you<\/span>/)
    noBanner(html)
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
    expect(text(mainOf(html))).not.toContain('On. Next run')
  })

  it('says a stop in the run’s own words in Recent runs, whatever the AI troubleshooter says', () => {
    const advice = { ...(troubleshooting as TroubleshootingOut), answers: { ...(troubleshooting as TroubleshootingOut).answers, what_happened: 'GitHub did not answer three times.' } }
    const html = render({ last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }], advice })
    expect(recentOf(html)).toContain("GitHub didn't answer")
    expect(text(mainOf(html))).not.toContain('GitHub did not answer')
    expect(text(mainOf(html))).not.toMatch(/write key/i)
  })

  it('gives an Approver the stop the same way, and lets them open the run', () => {
    const html = render({ me: BOB, last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }] })
    noBanner(html)
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
    expect(text(mainOf(html))).not.toMatch(/See why it stopped|Retry the run/)
  })

  it('while paused, holds Resume in the title row as the one primary action and has no Pause', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused' } })
    expect(mainOf(html)).toMatch(/_primary_[^>]*>(<svg[\s\S]*?<\/svg>)?Resume<\/button>/)
    expect(buttons(html)).not.toContain('Pause')
    expect(text(mainOf(html)).match(/Resume/g)).toHaveLength(1)
    expect(text(mainOf(html))).not.toContain('Paused. It won’t run until you resume it.')
  })

  it('tells everyone on its Summary who has it open in n8n, and offers no change the platform would refuse', () => {
    const held = { ...(openInN8n as UseCaseView), grade: 'needs_a_fix', findings: ['“Send email” is not a block we run.'] } as UseCaseView
    const html = render({ useCase: held })
    expect(text(html)).toMatch(/Carol has it open in n8n since (Mon 9 Nov, )?10:02\. Ask Carol, or anyone with n8n access, to take it back\./)
    expect(sectionText(html, 'When')).toContain('Can’t change it while Carol has it open in n8n.')
    const pressable = buttons(html)
    for (const refused of ['Undo', 'Add the approval step back', 'Change when it runs', 'Set when it runs', 'Resume']) expect(pressable, `${refused} would be refused`).not.toContain(refused)
    expect(pressable, 'Pause still works, so the safety lever never waits').toContain('Pause')
    expect(text(render({ me: BOB, useCase: held }))).toMatch(/Carol has it open in n8n since/)
  })

  it('says what a version that needs a fix must have fixed, in the safety checker’s words, with no Explain, even while someone has it open in n8n', () => {
    const findings = ['Its failures do not go to the platform’s error workflow.', 'n8n does not keep its test runs.']
    const held = { ...(openInN8n as UseCaseView), version: 1, grade: 'needs_a_fix', findings } as UseCaseView
    for (const me of [ALICE, BOB]) {
      const main = mainOf(render({ me, useCase: held }))
      const banner = /<div[^>]*data-tone="bad"[\s\S]*?<\/p><\/div>/.exec(main)?.[0] ?? ''
      expect(text(banner), me.id).toBe(`Needs a fix: ${findings.join(' ')} Anyone with n8n access can fix it in n8n.`)
      expect(banner, 'nothing to press: the findings say what to fix').not.toMatch(/<(?:a|button)\b/)
      expect(main, me.id).not.toContain('/explain')
      expect(text(main), me.id).not.toMatch(/\bExplain\b/)
    }
  })

  it('keeps Run now in More actions, never the main button, on a workflow with no schedule that needs a fix', () => {
    const fix = { ...AGENTS, version: 2, grade: 'needs_a_fix', findings: ['n8n does not keep its test runs.'] } as UseCaseView
    expect(buttons(render({ useCase: fix }))).not.toContain('Run now')
    expect(mainOf(render({ useCase: fix }))).not.toMatch(/_primary_[^>]*>(<svg[\s\S]*?<\/svg>)?Run now/)
  })

  it('goes back to the list', () => {
    expect(mainOf(render())).toMatch(/<a[^>]*href="\/workflows"[^>]*>[\s\S]*Workflows<\/a>/)
  })

  it('keeps Workflows marked in the menu', () => {
    const current = [...render().matchAll(/<a\b[^>]*aria-current="page"[^>]*>/g)].map((m) => /href="([^"]*)"/.exec(m[0])?.[1])
    expect(new Set(current)).toEqual(new Set(['/workflows']))
  })
})

const CHANGED = { useCase: versionedUseCase as UseCaseView, versions: changed.versions as VersionView[] }
const UNDONE = { useCase: undoneUseCase as UseCaseView, versions: undone.versions as VersionView[] }
const versionsOf = (html: string) => text(/<h2[^>]*>Versions<\/h2>([\s\S]*?)<\/section>/.exec(mainOf(html))?.[1] ?? '')

describe('the Versions list', () => {
  it('is not shown while the workflow has one version', () => {
    expect(text(mainOf(render()))).not.toContain('Versions')
  })

  it('lists each version newest first, with when, who and what changed, as the prototype says it', () => {
    expect(versionsOf(render(CHANGED))).toBe(
      'Version 2, in use Today, 9:10. Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00. ' +
        'Version 1 The version it was turned on with.',
    )
  })

  it('names an Undo as a new version that undid the one before', () => {
    expect(versionsOf(render(UNDONE))).toMatch(/^Version 3, in use Today, 9:12\. Alice undid version 2, so it runs every weekday at 8:00 again\. Version 2 Today, 9:10\. Alice changed .* to every Monday at 8:00\. Version 1/)
  })

  it('only reads, for an Operator and an Approver alike: Undo is on the chat’s edit card, as in the prototype', () => {
    for (const me of [ALICE, BOB]) {
      const html = render({ ...UNDONE, me })
      expect(versionsOf(html)).toContain('Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00.')
      expect(/<h2[^>]*>Versions<\/h2>[\s\S]*?<\/section>/.exec(mainOf(html))?.[0]).not.toMatch(/<button/)
      expect(buttons(html).filter((label) => label.startsWith('Undo'))).toEqual([])
    }
  })

  it('sits beside Recent runs, after it, with the buttons already up in the title row', () => {
    const html = mainOf(render(CHANGED))
    const order = ['>Pause<', 'Recent runs', '>Versions<'].map((needle) => html.indexOf(needle))
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it('shows the schedule the newest version runs on under When', () => {
    expect(whenOf(render(UNDONE))).toBe('Every weekday at 8:00 Singapore time (SGT).')
  })
})

describe('the rest of the workflow page', () => {
  it('has no Details fold: Versions is in view for an Operator and an Approver, and nothing is left for it to hold', () => {
    for (const me of [ALICE, BOB]) {
      const html = render({ me, ...CHANGED })
      expect(mainOf(html), me.id).not.toContain('<summary>Details')
      expect(mainOf(html), me.id).toContain('>Versions</h2>')
    }
    expect(mainOf(render())).not.toContain('>Versions<')
  })

  it('reads On · last run stopped on the page of an Operator whose work the run is not, as in the list', () => {
    expect(text(mainOf(render({ last: { you_can_open: false } })))).toContain('On · last run stopped')
  })

  it('says the one approval rule where the page names who says yes', () => {
    expect(text(mainOf(render()))).toContain('Who approves Any Approver but you, in Teams. Nothing is written until an Approver approves it.')
  })
})

describe('no Explain on the workflow page', () => {
  it('has no Explain link or button, on the page or on any version, for an Operator or an Approver', () => {
    for (const me of [ALICE, BOB]) {
      for (const shown of [render({ me }), render({ ...CHANGED, me })]) {
        expect(mainOf(shown), me.id).not.toContain('/explain')
        expect(text(mainOf(shown)), me.id).not.toMatch(/\bExplain\b/)
      }
    }
  })
})

describe('the Software watchlist', () => {
  const watched = { ...(statuses as WatchlistView), use_case_id: WATCHLIST.use_case_id }
  const own = (extra: Partial<UseCaseView> = {}, me: Me = ALICE, path?: string) => render({ me, useCase: { ...WATCHLIST, ...extra }, watchlist: watched, path })

  it('has a workflow page like any other, with its name, one of the four states and the list of its software', () => {
    const html = own()
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe(WATCHLIST.name)
    expect(text(mainOf(html))).toContain('On')
    for (const row of watched.software) expect(text(mainOf(html))).toContain(row.name)
  })

  it('gives an Operator Run now and Pause as any workflow has them, and no Check now and no Delete', () => {
    const main = mainOf(own())
    expect(buttons(main)).toContain('Pause')
    expect(buttons(main)).toContain('Run now')
    expect(buttons(main)).not.toContain('Check now')
    expect(buttons(main)).not.toContain('Delete')
    expect(main).not.toContain('Delete workflow')
  })

  it('gives Run now the quiet look, since the list is the page and a waiting yes leads it', () => {
    expect(mainOf(own())).not.toMatch(/<button[^>]*primary[^>]*>(?:<svg[\s\S]*?<\/svg>)?\s*Run now/)
  })

  it('shows no Run now while the list is empty, and none for a paused watchlist or an Approver', () => {
    const empty = { ...watched, software: [] }
    expect(buttons(mainOf(render({ useCase: WATCHLIST, watchlist: empty })))).not.toContain('Run now')
    expect(buttons(mainOf(own({ state: 'paused' })))).not.toContain('Run now')
    expect(buttons(mainOf(own({}, BOB)))).not.toContain('Run now')
  })

  it('says a stopped check once: one Open the run, not a second from the list', () => {
    const stopped = { ...watched, last_check: { ...statuses.last_check, state: 'failed' as const, run_id: STOPPED.run_id } } as WatchlistView
    const html = render({ useCase: WATCHLIST, last: {}, watchlist: stopped })
    expect(text(mainOf(html)).match(/Open the run/g)).toHaveLength(1)
  })

  it('says the n8n hold once, in the page’s own banner, and not again under the schedule', () => {
    const held = { ...WATCHLIST, held_in_n8n: { id: 'carol', name: 'Carol', since: '2026-11-04T05:40:00Z' } } as UseCaseView
    const html = render({ useCase: held, watchlist: watched })
    expect(html.match(/data-held/g)).toHaveLength(1)
    expect(text(mainOf(html))).not.toContain('Can’t change it while Carol has it open in n8n.')
    expect(buttons(mainOf(html))).not.toContain('Change schedule')
  })

  it('says it is moving to n8n once', () => {
    const html = render({ useCase: { ...WATCHLIST, moving_to_n8n: true } as UseCaseView, watchlist: { ...watched, moving_to_n8n: true } })
    expect(text(mainOf(html)).match(/Moving to n8n after this run\./g)).toHaveLength(1)
  })

  it('keeps the list in one column, with no empty half beside it', () => {
    expect(own()).not.toMatch(/class="[^"]*pair/)
  })

  it('gives an Operator Resume while it is paused, once', () => {
    const resumes = buttons(mainOf(own({ state: 'paused' }, ALICE))).filter((label) => label === 'Resume')
    expect(resumes).toHaveLength(1)
  })

  it('keeps adding and removing software on its page', () => {
    expect(text(mainOf(own()))).toContain('Add software')
    const row = watched.software[0]!
    expect(buttons(mainOf(own({}, ALICE, `/workflows/${WATCHLIST.use_case_id}?software=${row.id}`))).some((label) => label.startsWith('Remove from watchlist'))).toBe(true)
  })

  it('gives an Approver the list and no button', () => {
    const main = mainOf(own({}, BOB))
    expect(buttons(main)).not.toContain('Pause')
    expect(buttons(main)).not.toContain('Add software')
    expect(text(main)).toContain(watched.software[0]!.name)
  })
})

describe('a workflow that is not there', () => {
  it('says so and offers the list', () => {
    const html = render({ useCase: new ApiError(404, { detail: 'No such workflow' }) })
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe('Workflow not found')
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/workflows"[^>]*>Go to Workflows<\/a>/)
  })

  it('offers Try again when the platform had a problem', () => {
    expect(text(mainOf(render({ useCase: new ApiError(503, null) })))).toContain('Try again')
  })
})

describe('a draft tried on practice systems (ADR 0054)', () => {
  const DONE = (simulated as DraftedWorkflowView).simulation as SimulationView
  const DRAFT: UseCaseView = { ...AGENTS, state: 'draft' }

  it('shows its Check’s result on its page, beside Test run, for whoever reads it', () => {
    for (const me of [ALICE, BOB]) {
      const words = text(mainOf(render({ me, useCase: DRAFT, simulation: DONE })))
      expect(words).toContain('Tried 5 cases on practice systems: 4 passed.')
      expect(words).toContain('Turn on still runs the real test, which writes nothing.')
    }
  })

  it('shows nothing of practice systems once the workflow is on, or when there is nothing to try', () => {
    expect(text(mainOf(render({ useCase: { ...AGENTS, state: 'on' }, simulation: DONE })))).not.toContain('practice systems')
    expect(text(mainOf(render({ useCase: DRAFT, simulation: null })))).not.toContain('practice systems')
  })
})

describe('the page as the sketch lays it out', () => {
  const SCHEDULED: UseCaseView = { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: null } }
  const at = (html: string, needle: string) => html.indexOf(needle)
  const DRAFT: UseCaseView = { ...AGENTS, state: 'draft' }

  it('puts Change and Pause in the title row, before the sentence, and has no row of buttons at the foot', () => {
    const html = mainOf(render({ useCase: SCHEDULED }))
    expect(at(html, 'href="/?change=')).toBeGreaterThan(at(html, '<h1'))
    for (const needle of ['href="/?change=', '>Pause<', 'More actions']) expect(at(html, needle), needle).toBeLessThan(at(html, 'sentence'))
    expect(html).not.toMatch(/class="[^"]*_actions_/)
  })

  it('has one state mark and no banner while the workflow is simply On, and no banner for a stop', () => {
    const on = mainOf(render({ useCase: SCHEDULED }))
    expect(on).not.toMatch(/class="[^"]*_banner_/)
    expect(text(on)).not.toContain('On. Next run')
    const stopped = render({ useCase: SCHEDULED, last: {} })
    expect(mainOf(stopped)).not.toMatch(/class="[^"]*_banner_/)
    expect(mainOf(stopped)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
    expect(at(mainOf(stopped), 'Open the run')).toBeLessThan(at(mainOf(stopped), 'sentence'))
  })

  it('keeps the banner for a state the title row cannot say, such as a refused write', () => {
    const html = mainOf(render({ useCase: { ...SCHEDULED, move_refused: 'Not running. n8n did not take it yet.' } }))
    expect(html).toMatch(/class="[^"]*_banner_/)
  })

  it('puts Resume in the title row while paused, with no banner saying Paused twice', () => {
    const html = mainOf(render({ useCase: { ...AGENTS, state: 'paused' } }))
    expect(html).not.toMatch(/class="[^"]*_banner_/)
    expect(at(html, '>Resume<')).toBeLessThan(at(html, 'sentence'))
  })

  it('shows When, Who approves and Next run in one strip under the sentence, before the steps', () => {
    const html = mainOf(render({ useCase: SCHEDULED }))
    const order = ['sentence', '>When</h2>', '>Who approves</h2>', '>Next run</h2>', 'Check release'].map((needle) => at(html, needle))
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(sectionText(render({ useCase: SCHEDULED }), 'Next run')).toBe('Mon 9 Nov, 9:00')
    expect(sectionText(render({ useCase: SCHEDULED }), 'When')).not.toContain('Next run')
  })

  it('shows Recent runs and Versions side by side, with no Details fold and no Open button on a run', () => {
    const html = mainOf(render({ ...CHANGED, runs: [{ ...(done as RunView), use_case_id: CHANGED.useCase.use_case_id }] }))
    expect(html).not.toContain('<summary>Details')
    expect(at(html, '>Recent runs</h2>')).toBeLessThan(at(html, '>Versions</h2>'))
    expect(html).toMatch(/class="[^"]*_duo_[^"]*"[^>]*>\s*<section[\s\S]*>Recent runs<[\s\S]*>Versions</)
    expect(text(html)).not.toMatch(/Done Open/)
  })

  it('puts a draft’s Test run in the title row as its one primary button, with Change and More actions beside it', () => {
    const html = mainOf(render({ useCase: DRAFT }))
    expect(mainOf(html).match(/_primary_/g)).toHaveLength(1)
    expect(html).toMatch(/_primary_[^>]*>Test run<\/button>/)
    for (const needle of ['>Test run<', 'href="/?change=', 'More actions']) expect(at(html, needle), needle).toBeLessThan(at(html, 'sentence'))
    expect(html).not.toMatch(/class="[^"]*_actions_/)
  })

  it('shows a draft whose test run stopped as Draft alone, with no Test run mark and no Stopped banner', () => {
    const html = mainOf(render({ useCase: DRAFT, last: { test: true } }))
    expect(html).not.toMatch(/class="[^"]*_banner_/)
    expect(text(/<h1[\s\S]*?<p class="[^"]*sentence/.exec(html)?.[0] ?? '')).not.toContain('Test run Draft')
    expect((/data-life="draft"/g.exec(html) ?? []).length).toBe(1)
  })
})
