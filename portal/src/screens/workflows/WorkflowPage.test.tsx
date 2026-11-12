import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import troubleshooting from '../../../../contracts/fixtures/troubleshooting/failure.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import peopleList from '../../../../contracts/fixtures/people/list.json'
import versionedUseCase from '../../../../contracts/fixtures/builder/use-case.versioned.json'
import undoneUseCase from '../../../../contracts/fixtures/builder/use-case.undone.json'
import changed from '../../../../contracts/fixtures/builder/versions.json'
import undone from '../../../../contracts/fixtures/builder/versions.undone.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PersonOut, RunView, TroubleshootingOut, UseCaseView, VersionView } from '../../api/types'
import type { LastRun } from './workflow'
import { formatterFactory } from './workflow'
import { ScheduleChangePanel, WHO_APPROVES } from './WorkflowPage'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob', 'carol'].includes(person.id))

const AGENTS = agentUseCase as UseCaseView
const WATCHLIST = watchlistUseCase as UseCaseView
const NOW = new Date('2026-11-04T15:00:00+08:00')

const STOPPED: LastRun = { run_id: 'run_01JB9', state: 'failed', at: '2026-11-04T02:14:00Z', test: false, declined_by: null, proposed: 0, written: 0, tickets: false, you_can_decide: false, retryable: false, reason: 'AgentError' }

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

function renderPanel(useCase: UseCaseView): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <ScheduleChangePanel useCase={useCase} now={NOW} onSaved={() => undefined} onDone={() => undefined} />
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const buttons = (html: string) => [...mainOf(html).matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const factOf = (html: string, term: string) => text(new RegExp(`<dt>${term}</dt><dd>([\\s\\S]*?)</dd>`).exec(html)?.[1] ?? '')

/** The Schedule row's words, without who set it and without the next run. */
const whenOf = (html: string) => factOf(html, 'Schedule').replace(/ Next run: .*$/, '').replace(/ Set by \w+\.$/, '')
/** The next run, said in the Schedule row. */
const nextOf = (html: string) => /Next run: (.*)$/.exec(factOf(html, 'Schedule'))?.[1] ?? ''

describe('a workflow page', () => {
  it('shows its name, what it does, and whether it is on', () => {
    const html = render()
    expect(text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')).toBe('LangGraph release check')
    expect(text(mainOf(html))).toContain('Check langchain-ai/langgraph for a new release and raise a ticket in MOCK.')
    expect(mainOf(html)).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
  })

  it('says when it runs, when it runs next, and who may approve', () => {
    const html = render()
    expect(whenOf(html)).toBe('No schedule An Operator starts it with Run now.')
    expect(nextOf(html)).toBe('Not scheduled')
    expect(factOf(html, 'Approval')).toBe(`${WHO_APPROVES} Owned by Alice.`)
    expect(WHO_APPROVES).toBe('Any Approver except the people who start or own it')
  })

  it('gives its schedule’s day and time, and its next run', () => {
    const html = render({ useCase: { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(whenOf(html)).toBe('Every Monday at 9:00 Singapore time (SGT).')
    expect(nextOf(html)).toBe('Mon 9 Nov, 9:00')
  })

  it('for a London schedule, gives the next run in London time and says so, in the Schedule row and in Recent activity', () => {
    const london: UseCaseView = { ...AGENTS, next_run_at: '2026-11-04T09:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' } }
    const html = render({ useCase: london })
    expect(whenOf(html)).toBe('Every day at 9:00 London time.')
    expect(nextOf(html)).toBe('Today, 9:00 London time')
    expect(text(mainOf(html))).toContain('No runs yet. The first one is Today, 9:00 London time.')
  })

  it('for a London schedule, keeps each run’s start in Singapore time, as every time without a zone named is', () => {
    const london: UseCaseView = { ...AGENTS, next_run_at: '2026-11-04T09:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' } }
    const ran = { ...(done as RunView), use_case_id: london.use_case_id, started_at: '2026-11-03T09:00:00Z' }
    const html = render({ useCase: london, runs: [ran] })
    expect(nextOf(html)).toBe('Today, 9:00 London time')
    expect(text(mainOf(html))).toContain('Tue 3 Nov, 17:00 Done.')
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
      expect(text(mainOf(html))).toContain('The first one is Today, 15:00 Singapore time.')
    } finally {
      spy.mockRestore()
    }
  })

  it('while paused, keeps its schedule in the Schedule row and says Paused only for the next run', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused', next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice' } } })
    expect(whenOf(html)).toBe('Every Monday at 9:00 Singapore time (SGT).')
    expect(nextOf(html)).toBe('Paused')
  })

  it('while its schedule is held, keeps the schedule in the Schedule row and says for the next run why it is not running', () => {
    const removed = render({ useCase: { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_removed' } } })
    const notOperator = render({ useCase: { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_not_an_operator' } } })
    expect(whenOf(removed)).toBe('Every Monday at 9:00 Singapore time (SGT).')
    expect(nextOf(removed)).toBe('Not running: Alice is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(nextOf(notOperator)).toBe('Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.')
  })

  it('while paused and held, says Paused only, as the Software page does', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused', next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: 'owner_removed' } } })
    expect(nextOf(html)).toBe('Paused')
    expect(text(mainOf(html))).not.toContain('Not running')
  })

  it('names its agents, each opening its card in How it works', () => {
    const agents = /<h3>Agents<\/h3>([\s\S]*?)<\/section>/.exec(render())?.[1] ?? ''
    expect([...agents.matchAll(/<a[^>]*href="([^"]+)"/g)].map((m) => m[1])).toEqual([
      '/settings?tab=how&amp;show=agents&amp;agent=planner',
      '/settings?tab=how&amp;show=agents&amp;agent=crd_version_checker',
    ])
    expect(text(agents)).toBe('Planner Version checker')
  })

  it('names its agents without a link for an Approver, who is not offered How it works', () => {
    const agents = /<h3>Agents<\/h3>([\s\S]*?)<\/section>/.exec(render({ me: BOB }))?.[1] ?? ''
    expect(agents).not.toContain('<a')
    expect(text(agents)).toBe('Planner Version checker')
  })

  it('lists its steps, marking the one that changes data', () => {
    const said = text(mainOf(render()))
    expect(said).toContain('What it does')
    expect(said).toContain('Version checker Checks a public GitHub repository for a new release and proposes a Jira ticket for it. Reads only')
    expect(said).toContain('Create Jira tickets Create a Jira ticket, written only after approval. Changes data, waits for a yes')
  })

  it('gives an Operator Pause and a More actions button, and keeps Run now and Delete inside the closed menu', () => {
    const html = render()
    expect(buttons(html)).toEqual(expect.arrayContaining(['Pause', 'More actions']))
    expect(buttons(html)).not.toContain('Run now')
    expect(buttons(html)).not.toContain('Delete')
    expect(mainOf(html)).toMatch(/<button[^>]*aria-haspopup="menu"[^>]*aria-expanded="false"[^>]*>More actions/)
  })

  it('orders the page by decision: purpose, status banner, schedule, approval, recent activity, then Technical details', () => {
    const html = mainOf(render({ runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }] }))
    const at = (needle: string) => html.indexOf(needle)
    const order = [at('<h1'), at('data-tone='), at('<dt>Schedule</dt>'), at('<dt>Approval</dt>'), at('Recent activity'), at('Technical details')]
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it('keeps the steps and the agents folded under Technical details', () => {
    const html = mainOf(render())
    expect(html).toMatch(/<details[^>]*><summary>Technical details<\/summary>[\s\S]*What it does[\s\S]*<h3>Agents<\/h3>/)
    expect(html).not.toMatch(/<details[^>]*\bopen\b/)
  })

  const SCHEDULED: UseCaseView = { ...AGENTS, next_run_at: '2026-11-09T01:00:00Z', schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: null } }

  it('puts the schedule change beside the Schedule row, as Change, or Set when there is none', () => {
    expect(buttons(render({ useCase: SCHEDULED }))).toContain('Change schedule')
    expect(buttons(render())).toContain('Set schedule')
    expect(whenOf(render({ useCase: SCHEDULED }))).not.toContain('Change')
  })

  it('says in the Schedule row who set the schedule', () => {
    expect(factOf(render({ useCase: SCHEDULED }), 'Schedule')).toContain('Set by Carol.')
  })

  it('shows an Approver who is not an Operator neither schedule control', () => {
    for (const useCase of [SCHEDULED, AGENTS]) expect(buttons(render({ me: BOB, useCase })).filter((label) => /schedule/i.test(label))).toEqual([])
  })

  it('opens the form as a panel headed Change schedule that says the runs then count as the Operator’s work', () => {
    const html = renderPanel(SCHEDULED)
    expect(text(html)).toContain('Change schedule')
    expect(text(html)).toContain('Saving makes you the owner of this schedule. Its runs then count as your work, so you won’t be able to approve them.')
    expect(text(html)).toContain('Save schedule')
  })

  it('tells everyone a held schedule can be taken over by saving it', () => {
    const held: UseCaseView = { ...AGENTS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: 'owner_removed' } }
    for (const me of [ALICE, BOB]) {
      expect(nextOf(render({ me, useCase: held }))).toContain('An Operator can take it over by saving the schedule.')
    }
  })

  it('gives an Approver who may approve and the recent runs, but no manage buttons', () => {
    const html = render({ me: BOB, runs: [{ ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(factOf(html, 'Approval')).toContain(WHO_APPROVES)
    expect(text(mainOf(html))).toContain('Recent activity')
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
      expect(buttons(html).filter((label) => /Run now|Pause|Resume|Delete|More actions|Change|Set schedule|Turn/.test(label))).toEqual([])
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

  it('shows a stopped last run, linking to it', () => {
    const html = render({ last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }, { ...(done as RunView), use_case_id: 'uc_01JD0' }] })
    expect(mainOf(html)).toMatch(/data-tone="bad"[^>]*>.*Stopped<\/span>/)
    const first = /<li[^>]*data-run-id="([^"]+)"[^>]*data-state="([^"]+)"/.exec(html)
    expect([first?.[1], first?.[2]]).toEqual(['run_01JB9', 'failed'])
  })

  const bannerOfHtml = (html: string) => /<div[^>]*data-tone="bad"[\s\S]*?<\/(?:a|button)><\/div>/.exec(mainOf(html))?.[0] ?? ''

  it('for a retryable stop, the banner’s one action is Retry the run', () => {
    const banner = bannerOfHtml(render({ last: { retryable: true } }))
    expect(text(banner)).toBe('Stopped today at 10:14. An agent could not finish its work. Retry the run')
    expect(banner).toMatch(/<button[^>]*>Retry the run<\/button>/)
    expect(text(mainOf(render({ last: { retryable: true } })))).not.toContain('See why it stopped')
  })

  it('for a stop that cannot be retried, the banner’s one action is See why it stopped', () => {
    const html = render({ last: { retryable: false } })
    expect(text(bannerOfHtml(html))).toBe('Stopped today at 10:14. An agent could not finish its work. See why it stopped')
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>See why it stopped<\/a>/)
    expect(text(mainOf(html))).not.toContain('Retry the run')
  })

  it('says the same words as the Workflows list, whatever the AI troubleshooter says', () => {
    const advice = { ...(troubleshooting as TroubleshootingOut), answers: { ...(troubleshooting as TroubleshootingOut).answers, what_happened: 'GitHub did not answer three times.' } }
    const html = render({ last: { reason: 'TimedOut' }, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }], advice })
    expect(text(bannerOfHtml(html))).toContain('A step took too long.')
    expect(text(mainOf(html))).not.toContain('GitHub did not answer')
    expect(text(mainOf(html))).not.toMatch(/write key/i)
  })

  it('gives an Approver the stop in words, with no action', () => {
    const html = render({ me: BOB, last: {}, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JD0' }] })
    expect(mainOf(html)).toMatch(/data-tone="bad"/)
    expect(text(mainOf(html))).not.toMatch(/See why it stopped|Retry the run/)
  })

  it('while paused, holds Resume in the banner as the one primary action and has no Pause', () => {
    const html = render({ useCase: { ...AGENTS, state: 'paused' } })
    const banner = /<div[^>]*data-tone="off"[\s\S]*?<\/button><\/div>/.exec(mainOf(html))?.[0] ?? ''
    expect(text(banner)).toBe('Paused. It won’t run until you resume it. Resume')
    expect(buttons(html)).not.toContain('Pause')
    expect(text(mainOf(html)).match(/Resume/g)).toHaveLength(1)
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
const versionsOf = (html: string) => text(/<section[^>]*><h2[^>]*>Versions<\/h2>([\s\S]*?)<\/section>/.exec(mainOf(html))?.[1] ?? '')

describe('the Versions list', () => {
  it('is not shown while the workflow has one version', () => {
    expect(text(mainOf(render()))).not.toContain('Versions')
  })

  it('lists each version newest first, with when, who and what changed, as the prototype says it', () => {
    expect(versionsOf(render(CHANGED))).toBe(
      'Version 2 Today, 9:10. Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00. This is the version running now. ' +
        'Version 1 The version it was turned on with.',
    )
  })

  it('names an Undo as a new version that undid the one before', () => {
    expect(versionsOf(render(UNDONE))).toMatch(/^Version 3 Today, 9:12\. Alice undid version 2, so it runs every weekday at 8:00 again\. This is the version running now\. Version 2 Today, 9:10\. Alice changed .* to every Monday at 8:00\. Version 1/)
  })

  it('only reads, for an Operator and an Approver alike: Undo is on the chat’s edit card, as in the prototype', () => {
    for (const me of [ALICE, BOB]) {
      const html = render({ ...UNDONE, me })
      expect(versionsOf(html)).toContain('Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00.')
      expect(/<h2[^>]*>Versions<\/h2>[\s\S]*?<\/section>/.exec(mainOf(html))?.[0]).not.toMatch(/<button/)
      expect(buttons(html).filter((label) => label.startsWith('Undo'))).toEqual([])
    }
  })

  it('sits after Recent activity and before Technical details, as the spec orders the page', () => {
    const html = mainOf(render(CHANGED))
    const order = ['Recent activity', '>Versions<', 'Technical details'].map((needle) => html.indexOf(needle))
    expect(order.every((place) => place >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it('shows the schedule the newest version runs on in the Schedule row', () => {
    expect(whenOf(render(UNDONE))).toBe('Every weekday at 8:00 Singapore time (SGT).')
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
