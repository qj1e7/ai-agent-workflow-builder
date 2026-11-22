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
import { App } from '../../App'
import { ApiError, type ApiClient } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PersonOut, RunView, TroubleshootingOut, UseCaseView, VersionView } from '../../api/types'
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

const STOPPED: LastRun = { run_id: 'run_01JB9', state: 'failed', at: '2026-11-04T02:14:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: false, you_can_decide: false, retryable: false, reason: 'AgentError', stop: { at: '2026-11-04T02:14:00Z', what_happened: 'An agent could not finish its work.' } }

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
}

function render({ me = ALICE, useCase: given = AGENTS, runs = [], id, advice, last, versions }: Setup = {}): string {
  const useCase = last && !(given instanceof Error) ? { ...given, last_run: { ...STOPPED, ...last } } : given
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const useCaseId = id ?? (useCase instanceof Error ? 'uc_gone' : useCase.use_case_id)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['people', scope], TEAM)
  queryClient.setQueryData(['runs', scope], runs)
  const stopped = runs.find((run) => run.use_case_id === useCaseId && run.state === 'failed')
  if (advice && stopped?.state === 'failed') queryClient.setQueryData(['troubleshoot', scope, stopped.run_id, stopped.last_seq], advice)
  const key = ['use-case', scope, useCaseId]
  if (useCase instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: useCase, fetchStatus: 'idle' })
  else queryClient.setQueryData(key, useCase)
  if (versions && !(useCase instanceof Error)) queryClient.setQueryData(['versions', scope, useCaseId, useCase.version], versions)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[`/workflows/${useCaseId}`]}>
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
/** The next run, said under When. */
const nextOf = (html: string) => /(?:Next run: |(?=Not running: ))(.*)$/.exec(sectionText(html, 'When'))?.[1] ?? ''
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
    expect(sentenceOfHtml(render())).toBe('Check langchain-ai/langgraph on GitHub for a new release when an Operator presses Run now. If there is one, create an upgrade ticket in Jira project MOCK, after a yes.')
    const html = render({ useCase: { ...AGENTS, next_run_at: '2026-11-05T00:00:00Z', schedule: { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(sentenceOfHtml(html)).toBe('Every day at 8:00, check langchain-ai/langgraph on GitHub for a new release. If there is one, create an upgrade ticket in Jira project MOCK, after a yes.')
  })

  it('draws its steps as the run line, large, with a tag under each', () => {
    const line = text(/<div[^>]*class="[^"]*large[^"]*"[\s\S]*?<\/ol>/.exec(mainOf(render()))?.[0] ?? '')
    expect(line).toContain('Run now No system access')
    expect(line).toContain('Check release Reads only')
    expect(line).toContain('Ask for a yes Waits for a yes')
    expect(line).toContain('Create Jira tickets Writes after a yes')
  })

  it('keeps what it was set up without as a Left out line, and none when nothing was left out', () => {
    const line = 'Left out: “colour them by team”. It was set up without that part.'
    expect(text(mainOf(render({ useCase: leftOutUseCase as UseCaseView })))).toContain(line)
    expect(text(mainOf(render()))).not.toContain('Left out')
  })

  it('says when it runs, when it runs next, and who says yes', () => {
    const html = render()
    expect(whenOf(html)).toBe('No schedule An Operator starts it with Run now.')
    expect(nextOf(html)).toBe('Not scheduled')
    expect(sectionText(html, 'Who says yes')).toBe('Any Approver but you, in Teams. Nothing is written until an Approver says yes. Who can’t say yes Nobody says yes to their own work. The workflow’s owner, whoever starts a run and whoever retries it can’t say yes to that run.')
  })

  it('keeps the sketch’s short Who says yes line, with the whole own-work rule folded one tap away', () => {
    const rule = /<details[^>]*>\s*<summary>Who can’t say yes<\/summary>([\s\S]*?)<\/details>/.exec(mainOf(render({ useCase: SCHEDULED })))
    expect(text(rule?.[1] ?? '')).toBe('Nobody says yes to their own work. The workflow’s owner, whoever starts a run and whoever retries it can’t say yes to that run. A scheduled run starts as Carol.')
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

  it('orders the page as the sketch does: the sentence, the banner, the line, When, Who says yes, Recent runs, then the buttons, with no Agents section', () => {
    const html = mainOf(render({ runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }] }))
    const at = (needle: string) => html.indexOf(needle)
    const order = [at('<h1'), at('sentence'), at('data-tone='), at('Check release'), at('>When</h2>'), at('>Who says yes</h2>'), at('>Recent runs</h2>'), at('>Pause<')]
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(html).not.toContain('Agents')
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
    expect(sectionText(html, 'Who says yes')).toMatch(/^Any Approver but Alice, in Teams\. Who can’t say yes /)
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

  it('opens the run from the banner for someone who may not decide a waiting run, and decides for someone who may', () => {
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

  const bannerOfHtml = (html: string) => /<div[^>]*data-tone="bad"[\s\S]*?<\/(?:a|button)><\/div>/.exec(mainOf(html))?.[0] ?? ''

  it('for a stop, retryable or not, the banner’s one action is Open the run, as in the sketch', () => {
    for (const retryable of [true, false]) {
      const html = render({ last: { retryable } })
      expect(text(bannerOfHtml(html))).toBe('Stopped today at 10:14. An agent could not finish its work. Open the run')
      expect(bannerOfHtml(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>Open the run<\/a>/)
      expect(text(mainOf(html))).not.toMatch(/Retry the run|See why it stopped/)
    }
  })

  it('for a run n8n lost, says Lost in the pill and in the banner, never On', () => {
    const html = render({ last: { state: 'lost', reason: null } })
    expect(mainOf(html)).toMatch(/data-tone="bad"[^>]*>.*Lost<\/span>/)
    expect(text(bannerOfHtml(html))).toBe('Lost today at 10:14. Approved, but the run stopped before it could make the change. Nothing was written. Open the run')
    expect(text(mainOf(html))).not.toContain('On. Next run')
  })

  it('says the same words as the Workflows list, whatever the AI troubleshooter says', () => {
    const advice = { ...(troubleshooting as TroubleshootingOut), answers: { ...(troubleshooting as TroubleshootingOut).answers, what_happened: 'GitHub did not answer three times.' } }
    const waited = 'The run waited too long for the workflow engine and gave up.'
    const html = render({ last: { reason: 'TimedOut', stop: { at: '2026-11-04T02:14:00Z', what_happened: waited } }, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }], advice })
    expect(text(bannerOfHtml(html))).toContain(waited)
    expect(text(mainOf(html))).not.toContain('GitHub did not answer')
    expect(text(mainOf(html))).not.toMatch(/write key/i)
  })

  it('gives an Approver the stop in the same words, and lets them open the run', () => {
    const html = render({ me: BOB, last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }] })
    expect(text(bannerOfHtml(html))).toBe('Stopped today at 10:14. An agent could not finish its work. Open the run')
    expect(text(mainOf(html))).not.toMatch(/See why it stopped|Retry the run/)
  })

  it('while paused, holds Resume in the banner as the one primary action and has no Pause', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused' } })
    const banner = /<div[^>]*data-tone="off"[\s\S]*?<\/button><\/div>/.exec(mainOf(html))?.[0] ?? ''
    expect(text(banner)).toBe('Paused. It won’t run until you resume it. Resume')
    expect(buttons(html)).not.toContain('Pause')
    expect(text(mainOf(html)).match(/Resume/g)).toHaveLength(1)
  })

  it('tells everyone on its Summary who has it open in n8n, and offers no change the platform would refuse', () => {
    const held = { ...(openInN8n as UseCaseView), grade: 'needs_a_fix', findings: ['“Send email” is not a block we run.'] } as UseCaseView
    const html = render({ useCase: held })
    expect(text(html)).toMatch(/Carol has it open in n8n since (Mon 9 Nov, )?10:02\. Ask Carol, or anyone with n8n access, to take it back\./)
    expect(sectionText(html, 'When')).toContain('Can’t change it while Carol has it open in n8n.')
    const pressable = buttons(html)
    for (const refused of ['Undo', 'Add the yes back', 'Change when it runs', 'Set when it runs', 'Resume']) expect(pressable, `${refused} would be refused`).not.toContain(refused)
    expect(pressable, 'Pause still works, so the safety lever never waits').toContain('Pause')
    expect(text(render({ me: BOB, useCase: held }))).toMatch(/Carol has it open in n8n since/)
  })

  it('says a version that needs a fix in one sentence, with one way forward to Explain’s flags, even while someone has it open in n8n', () => {
    const findings = ['Its failures do not go to the platform’s error workflow.', 'n8n does not keep its test runs.']
    const held = { ...(openInN8n as UseCaseView), version: 1, grade: 'needs_a_fix', findings } as UseCaseView
    for (const me of [ALICE, BOB]) {
      const banner = /<div[^>]*data-tone="bad"[\s\S]*?<\/a><\/div>/.exec(mainOf(render({ me, useCase: held })))?.[0] ?? ''
      expect(text(banner)).toBe('Needs a fix. Explain')
      expect(banner).toMatch(new RegExp(`href="/workflows/${held.use_case_id}/explain#flags"`))
      for (const finding of findings) expect(text(banner)).not.toContain(finding)
      const explains = [...mainOf(render({ me, useCase: held })).matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)].filter((m) => text(m[1] ?? '').startsWith('Explain'))
      expect(explains, 'one Explain on the page: the banner’s').toHaveLength(1)
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
const versionsOf = (html: string) => text(/<h3[^>]*>Versions<\/h3>([\s\S]*?)<\/section>/.exec(mainOf(html))?.[1] ?? '')

describe('the Versions list', () => {
  it('is not shown while the workflow has one version', () => {
    expect(text(mainOf(render()))).not.toContain('Versions')
  })

  it('lists each version newest first, with when, who and what changed, as the prototype says it', () => {
    expect(versionsOf(render(CHANGED))).toBe(
      'Version 2, in use Today, 9:10. Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00. Explain LangGraph release check, version 2 ' +
        'Version 1 The version it was turned on with. Explain LangGraph release check, version 1',
    )
  })

  it('names an Undo as a new version that undid the one before', () => {
    expect(versionsOf(render(UNDONE))).toMatch(/^Version 3, in use Today, 9:12\. Alice undid version 2, so it runs every weekday at 8:00 again\. Explain LangGraph release check, version 3 Version 2 Today, 9:10\. Alice changed .* to every Monday at 8:00\. Explain LangGraph release check, version 2 Version 1/)
  })

  it('only reads, for an Operator and an Approver alike: Undo is on the chat’s edit card, as in the prototype', () => {
    for (const me of [ALICE, BOB]) {
      const html = render({ ...UNDONE, me })
      expect(versionsOf(html)).toContain('Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00.')
      expect(/<h3[^>]*>Versions<\/h3>[\s\S]*?<\/section>/.exec(mainOf(html))?.[0]).not.toMatch(/<button/)
      expect(buttons(html).filter((label) => label.startsWith('Undo'))).toEqual([])
    }
  })

  it('sits after Recent runs and the buttons, inside Details, as the prototype orders the page', () => {
    const html = mainOf(render(CHANGED))
    const order = ['Recent runs', '>Pause<', '>Details<', '>Versions<'].map((needle) => html.indexOf(needle))
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it('shows the schedule the newest version runs on under When', () => {
    expect(whenOf(render(UNDONE))).toBe('Every weekday at 8:00 Singapore time (SGT).')
  })
})

describe('Details on the workflow page', () => {
  const detailsOf = (html: string) => /<details[^>]*>\s*<summary[^>]*>Details<\/summary>[\s\S]*?<\/details>/.exec(mainOf(html))?.[0] ?? ''

  it('holds Explain and Versions, and nothing the person needs in view', () => {
    const html = render(CHANGED)
    const details = detailsOf(html)
    expect(text(details)).toMatch(/^Details Explain LangGraph release check .*Versions Version 2/)
    expect(details).not.toMatch(/Pause|Run now|Open in n8n|Delete/)
    expect(mainOf(html).replace(details, '')).not.toMatch(/\/explain|>Versions</)
  })

  it('is closed until opened, and is there for an Approver too', () => {
    for (const me of [ALICE, BOB]) expect(detailsOf(render({ me, ...CHANGED })), me.id).not.toMatch(/<details[^>]*\bopen/)
  })

  it('leaves out an empty Details: a first version has Explain only, and the banner’s Explain is the one on the page', () => {
    expect(text(detailsOf(render()))).toBe('Details Explain Agents release check')
  })

  it('says the one approval rule where the page names who says yes', () => {
    expect(text(mainOf(render()))).toContain('Who says yes Any Approver but you, in Teams. Nothing is written until an Approver says yes.')
  })
})

describe('Explain on the workflow page', () => {
  const explainLinks = (html: string) => [...mainOf(html).matchAll(/<a\b[^>]*href="([^"]*\/explain[^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [text(m[2] ?? ''), m[1]])

  it('puts Explain in the page’s actions for an Operator and for an Approver', () => {
    for (const me of [ALICE, BOB]) {
      expect(explainLinks(render({ me })), me.id).toEqual([[`Explain ${AGENTS.name}`, `/workflows/${AGENTS.use_case_id}/explain`]])
    }
  })

  it('puts Explain on each version, with that version, for both roles', () => {
    for (const me of [ALICE, BOB]) {
      const id = CHANGED.useCase.use_case_id
      const name = CHANGED.useCase.name
      expect(explainLinks(render({ ...CHANGED, me })), me.id).toEqual([
        [`Explain ${name}, version 2`, `/workflows/${id}/explain?version=2`],
        [`Explain ${name}, version 1`, `/workflows/${id}/explain?version=1`],
        [`Explain ${name}`, `/workflows/${id}/explain`],
      ])
    }
  })
})

describe('the Software watchlist', () => {
  it('has no workflow page of its own, so its address sends the person to the Software page', () => {
    for (const me of [ALICE, BOB]) {
      const main = mainOf(render({ me, useCase: WATCHLIST }))
      expect(main).not.toMatch(/<h1\b/)
      expect(buttons(main)).toEqual([])
    }
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
