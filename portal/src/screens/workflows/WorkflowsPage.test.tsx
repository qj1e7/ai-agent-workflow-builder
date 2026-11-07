import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import waiting from '../../../../contracts/fixtures/views/success.awaiting_approval.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import draftsFixture from '../../../../contracts/fixtures/builder/drafts.json'
import type { DraftView, HomeOut, Me, ReplyView, RunView, TeamRequestView, UseCaseView } from '../../api/types'
import { needsTotal } from '../home/home'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const CAROL: Me = { id: 'carol', display: 'Carol', roles: ['operator'] }

const WATCHLIST = watchlistUseCase as UseCaseView
const LANGGRAPH: UseCaseView = { ...(agentUseCase as UseCaseView), use_case_id: 'uc_lang', state: 'paused' }
const BUGS: UseCaseView = { ...(agentUseCase as UseCaseView), use_case_id: 'uc_bugs', name: 'Morning bug report check', instruction: 'Raise a ticket for each new bug report.' }
const RUNS = [
  { ...(failed as RunView), use_case_id: 'uc_bugs', run_id: 'run_bugs' },
  waiting as RunView,
  { ...(done as RunView), run_id: 'run_older', started_at: '2026-11-01T02:14:00Z' },
]

const NOW = new Date('2026-11-04T15:00:00+08:00')

interface Setup {
  readonly me?: Me
  readonly useCases?: UseCaseView[] | Error | 'loading'
  readonly runs?: RunView[]
  readonly state?: unknown
  readonly home?: HomeOut
  readonly drafts?: DraftView[]
  readonly request?: { readonly id: string; readonly data?: TeamRequestView | Error }
}

/** The platform answers for the person asking. In these tests only Bob may decide the waiting run. */
const asSeenBy = (me: Me, runs: RunView[]): RunView[] =>
  runs.map((run) => (run.state === 'awaiting_approval' ? { ...run, you_can_decide: me.id === 'bob' } : run))

function render({ me = ALICE, useCases = [BUGS, WATCHLIST, LANGGRAPH], runs = RUNS, state, home, drafts, request }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB, CAROL])
  queryClient.setQueryData(['runs', scope], asSeenBy(me, runs))
  if (home) queryClient.setQueryData(['home', scope], home)
  if (drafts) queryClient.setQueryData(['drafts', scope], drafts)
  if (request?.data instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['team-request', scope, request.id] }).setState({ status: 'error', error: request.data, fetchStatus: 'idle' })
  else if (request?.data) queryClient.setQueryData(['team-request', scope, request.id], request.data)
  if (useCases instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['use-cases', scope] }).setState({ status: 'error', error: useCases, fetchStatus: 'idle' })
  else if (useCases !== 'loading') queryClient.setQueryData(['use-cases', scope], useCases)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[{ pathname: '/workflows', search: request ? `?request=${request.id}` : '', state }]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
function rowOf(html: string, id: string): string {
  return new RegExp(`<li[^>]*data-workflow-id="${id}"[\\s\\S]*?</li>`).exec(html)?.[0] ?? ''
}

describe('the Workflows list', () => {
  it('shows each workflow, whether it is on or paused, and its latest run, as separate facts', () => {
    const html = render()
    const bugs = rowOf(html, 'uc_bugs')
    expect(bugs).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
    expect(bugs).toMatch(/data-tone="bad"[^>]*>.*Stopped<\/span>/)
    expect(text(bugs)).toContain('Morning bug report check')
    expect(text(bugs)).toContain('Raise a ticket for each new bug report.')
    const watchlist = rowOf(html, 'uc_01JB7')
    expect(watchlist).toMatch(/data-tone="wait"[^>]*>.*Needs a yes<\/span>/)
    expect(text(watchlist)).toContain('Check the team\'s watched software for new releases')
    const paused = rowOf(html, 'uc_lang')
    expect(paused).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
    expect(text(paused)).toContain('Check langchain-ai/langgraph for a new release')
  })

  it('shows the next run beside it: a date, Paused, or Not scheduled', () => {
    const html = render()
    expect(text(rowOf(html, 'uc_01JB7'))).toContain('Next: Mon 9 Nov, 9:00')
    expect(text(rowOf(html, 'uc_lang'))).toContain('Next: Paused')
    expect(text(rowOf(html, 'uc_bugs'))).toContain('Not scheduled')
  })

  it('for a London schedule, names London next to its next run, and keeps its latest run’s start in Singapore time', () => {
    const london: UseCaseView = { ...BUGS, next_run_at: '2026-11-04T09:00:00Z', schedule: { day: 'every_day', at: '09:00', time_zone: 'Europe/London', owner_name: 'Alice' } }
    const ran = { ...(done as RunView), use_case_id: 'uc_bugs', started_at: '2026-11-04T06:00:00Z' }
    const row = text(rowOf(render({ useCases: [london], runs: [ran] }), 'uc_bugs'))
    expect(row).toContain('Next: Today, 9:00 London time')
  })

  it('promises no next run on a row whose schedule is held, because its owner can no longer run it', () => {
    const held: UseCaseView = { ...BUGS, next_run_at: null, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Carol', held: 'owner_removed' } }
    const row = text(rowOf(render({ useCases: [held] }), 'uc_bugs'))
    expect(row).toContain('Not running')
    expect(row).not.toContain('Next:')
    expect(row).not.toContain('Not scheduled')
  })

  it('opens each workflow from its name, and the Software watchlist on the Software page', () => {
    const html = render()
    expect(rowOf(html, 'uc_bugs')).toMatch(/<a[^>]*href="\/workflows\/uc_bugs"[^>]*>Morning bug report check<\/a>/)
    expect(rowOf(html, 'uc_01JB7')).toMatch(/<a[^>]*href="\/software"[^>]*>Software watchlist<\/a>/)
  })

  it('puts the rows that need you first, each with its one button', () => {
    const forCarol = render({ me: CAROL })
    expect([...forCarol.matchAll(/data-workflow-id="([^"]+)"/g)].map((m) => m[1])).toEqual(['uc_bugs', 'uc_01JB7', 'uc_lang'])
    expect(rowOf(forCarol, 'uc_bugs')).toMatch(/<a[^>]*href="\/runs\/run_bugs"[^>]*>See why it stopped<\/a>/)
    const forBob = render({ me: BOB })
    expect([...forBob.matchAll(/data-workflow-id="([^"]+)"/g)].map((m) => m[1])).toEqual(['uc_01JB7', 'uc_bugs', 'uc_lang'])
    expect(rowOf(forBob, 'uc_01JB7')).toMatch(/<a[^>]*href="\/runs\/run_01JB8"[^>]*>Review and decide<\/a>/)
    expect(text(rowOf(forBob, 'uc_bugs'))).not.toContain('See why it stopped')
  })

  it('offers alice nothing to decide on a run she started', () => {
    expect(text(rowOf(render(), 'uc_01JB7'))).not.toContain('Review and decide')
  })

  it('draws no agent faces and no step details in a row', () => {
    const main = mainOf(render())
    expect(main).not.toContain('data-state=')
    expect(main).not.toContain('/agents/')
  })

  it('hides the search box and the filters until the search button is pressed', () => {
    const main = mainOf(render())
    expect(main).not.toContain('find-workflows')
    expect(main).not.toContain('aria-pressed')
    expect(main).toMatch(/<button[^>]*aria-expanded="false"[^>]*aria-controls="findbar-workflows"[^>]*aria-label="Search workflows"/)
  })

  it('looks the same to an Approver apart from the row buttons, and has no change controls', () => {
    const main = text(mainOf(render({ me: BOB })))
    expect(main).toContain('Morning bug report check')
    expect(main).not.toMatch(/\bPause\b|\bResume\b|\bDelete\b|Run now/)
  })

  it('says when there is nothing yet, in words for the person reading', () => {
    expect(text(mainOf(render({ useCases: [] })))).toContain('Nothing here yet Ask the Planner on Home, and your first workflow shows up here.')
    expect(text(mainOf(render({ useCases: [], me: BOB })))).toContain('Operators set up workflows, and you approve their changes.')
    expect(mainOf(render({ useCases: [] }))).not.toContain('aria-controls="findbar-workflows"')
  })

  it('says the list could not be loaded and offers Try again', () => {
    const main = text(mainOf(render({ useCases: new ApiError(503, null) })))
    expect(main).toContain('The workflows could not be loaded.')
    expect(main).toContain('Try again')
  })
})

describe('after a delete', () => {
  const deleted = { deleted: { id: 'uc_gone', name: 'Stale ticket nudge' } }

  it('says what was deleted, with Undo and no time limit', () => {
    const html = render({ state: deleted })
    expect(text(html)).toContain('Deleted Stale ticket nudge.')
    expect(html).toMatch(/<button[^>]*id="toast-undo"[^>]*>Undo<\/button>/)
    expect(html).toContain('aria-label="Dismiss"')
  })

  it('tells the shell that the page moves focus itself, so focus can go to Undo', () => {
    const heading = (html: string) => /<h1\b[^>]*>/.exec(html)?.[0] ?? ''
    expect(heading(render({ state: deleted }))).toContain('data-page-moves-focus')
    expect(heading(render())).not.toContain('data-page-moves-focus')
  })

  it('draws the heading the same while the list loads and once it has loaded, so the shell’s focus stays on it', () => {
    const heading = (html: string) => /<h1\b[^>]*>[\s\S]*?<\/h1>/.exec(mainOf(html))?.[0] ?? ''
    for (const state of [undefined, deleted]) {
      const loading = render({ state, useCases: 'loading' })
      expect(text(mainOf(loading))).toContain('Loading the workflows')
      expect(heading(loading), JSON.stringify(state)).toBe(heading(render({ state })))
    }
  })

  it('shows no message on an ordinary visit', () => {
    expect(render()).not.toContain('toast-undo')
  })
})

const navNames = (html: string) =>
  [...html.matchAll(/<nav\b[^>]*aria-label="Main"[^>]*>([\s\S]*?)<\/nav>/g)].flatMap((nav) => [...(nav[1] ?? '').matchAll(/<a\b([^>]*)>/g)].map((a) => /aria-label="([^"]*)"/.exec(a[1] ?? '')?.[1] ?? ''))
const primaries = (html: string) => (html.match(/<(?:a|button)\b[^>]*class="[^"]*_primary_[^"]*"[^>]*>/g) ?? []).length
const labelsOf = (html: string, ...label: string[]) => label.flatMap((words) => [...html.matchAll(new RegExp(`>${words}<`, 'g'))])

describe('one action per workflow on Workflows', () => {
  it('keeps one primary button when Needs you lists the Operator’s stopped run, and offers no row button for it', () => {
    const html = render({ home: aliceHome as HomeOut, runs: [{ ...(failed as RunView), use_case_id: 'uc_01JB7', run_id: 'run_01JB9' }] })
    expect(primaries(mainOf(html))).toBe(1)
    expect(rowOf(html, 'uc_01JB7')).not.toMatch(/See why it stopped|Review and decide/)
  })

  it('keeps one primary button when Needs you lists the Approver’s approval, and no second Review and decide', () => {
    const html = render({ me: BOB, home: bobHome as HomeOut })
    expect(primaries(mainOf(html))).toBe(1)
    expect(labelsOf(html, 'Review and decide')).toHaveLength(1)
    expect(rowOf(html, 'uc_01JB7')).not.toContain('Review and decide')
  })

  it('still offers a row its button when Needs you does not list that run', () => {
    const quiet: HomeOut = { ...(bobHome as HomeOut), approvals: [], approvals_total: 0, confirmations: [], stopped: [], stopped_total: 0, replied: [] }
    const html = render({ me: BOB, home: quiet })
    expect(primaries(mainOf(html))).toBe(1)
    expect(rowOf(html, 'uc_01JB7')).toContain('Review and decide')
  })
})

describe('Needs you at the top of Workflows', () => {
  const HOME = aliceHome as HomeOut

  it('lists what needs the person in full, with the same total as the tab', () => {
    const html = render({ home: HOME })
    const total = needsTotal(HOME)
    const section = /<section[^>]*aria-labelledby="[^"]*"[\s\S]*?<\/section>/.exec(html)?.[0] ?? ''
    expect(text(section)).toContain(`Needs you ${total}`)
    expect(section).toContain('data-home-item="stopped:run_01JB9"')
    expect(navNames(html).filter((name) => name.startsWith('Workflows'))).toEqual([`Workflows, ${total} need you`, `Workflows, ${total} need you`])
    expect(html.indexOf('aria-label="Needs you"')).toBeLessThan(html.indexOf('aria-label="Workflows"'))
  })

  it('shows no section when nothing needs the person', () => {
    const quiet: HomeOut = { ...HOME, approvals: [], approvals_total: 0, confirmations: [], stopped: [], stopped_total: 0, replied: [] }
    expect(render({ home: quiet })).not.toContain('aria-label="Needs you"')
    expect(render()).not.toContain('aria-label="Needs you"')
  })
})


const REPLY: ReplyView = { replied_by: 'bob', replied_by_name: 'Bob', replied_at: '2026-11-04T08:30:00Z', text: 'Looking into it.', status: 'answered' }
const REQUEST: TeamRequestView = {
  request_id: 'trq_01JD5RP',
  kind: 'support',
  about: { run_id: 'run_01JB9' },
  note: 'It stopped again.',
  asked_by: 'alice',
  asked_by_name: 'Alice',
  asked_at: '2026-11-04T07:02:00Z',
  status: 'answered',
  replies: [REPLY],
  posted_to_teams: true,
  not_posted_because: null,
}
const sectionOf = (html: string, name: string) => new RegExp(`<section[^>]*data-section="${name}"[\\s\\S]*?</section>`).exec(html)?.[0] ?? ''

describe('the sections under Needs you', () => {
  const HOME = aliceHome as HomeOut
  const DRAFTS = draftsFixture.drafts as DraftView[]

  it('come in order: Needs you, Drafts, Waiting on others, Following up, All workflows', () => {
    const html = mainOf(render({ home: HOME, drafts: DRAFTS }))
    const at = ['aria-label="Needs you"', 'data-section="drafts"', 'data-section="waiting"', 'data-section="following"', 'aria-labelledby="all-workflows-h"'].map((marker) => html.indexOf(marker))
    expect(at.every((index) => index >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
  })

  it('lists a draft with its step, Resume and Discard, each named for the draft', () => {
    const drafts = sectionOf(mainOf(render({ home: HOME, drafts: DRAFTS })), 'drafts')
    expect(text(drafts)).toContain('Drafts 1')
    expect(text(drafts)).toContain('Nudge stale tickets Step 2 of 4. Last saved Today, 14:24.')
    expect(drafts).toMatch(/<a[^>]*href="\/new\?draft=drf-7f3a2c"[^>]*>Resume<span[^>]*> Nudge stale tickets<\/span><\/a>/)
    expect(drafts).toMatch(/<button[^>]*>Discard<span[^>]*> Nudge stale tickets<\/span><\/button>/)
  })

  it('shows no Drafts section without drafts, and none to an Approver who is not an Operator', () => {
    expect(render({ home: HOME, drafts: [] })).not.toContain('data-section="drafts"')
    expect(render({ me: BOB, home: bobHome as HomeOut, drafts: DRAFTS })).not.toContain('data-section="drafts"')
  })

  it('moves Waiting on others here from Home, with no Approve button', () => {
    const waitingSection = sectionOf(mainOf(render({ home: HOME })), 'waiting')
    expect(text(waitingSection)).toContain('Waiting on others An Approver’s yes on Software watchlist You started it')
    expect(waitingSection).toContain('href="/runs/run_01JB8"')
    expect(waitingSection).not.toContain('<button')
  })

  it('lists the person’s requests under Following up with the status and the latest reply, each opening that request', () => {
    const following = sectionOf(mainOf(render({ home: HOME })), 'following')
    expect(text(following)).toContain('It stopped again. Platform problem')
    expect(text(following)).toContain('Answered by Bob: Looking into it.')
    expect(following).toContain('href="/workflows?request=trq_01JD5RP"')
  })

  it('says how many requests Following up shows when there are more than the platform lists, and never offers a link that goes nowhere', () => {
    const many: HomeOut = { ...HOME, following_up_total: 63, waiting_on_others_total: 61 }
    const html = render({ home: many })
    expect(text(sectionOf(mainOf(html), 'following'))).toContain('Showing the newest 1 of 63.')
    expect(text(sectionOf(mainOf(html), 'waiting'))).toContain('Showing the newest 1 of 61.')
    expect(text(sectionOf(mainOf(render({ home: HOME })), 'following'))).not.toContain('Showing the newest')
  })

  it('shows a reply the person has not opened in Needs you, with the same count as the tab', () => {
    const html = render({ home: HOME })
    expect(mainOf(html)).toContain('data-home-item="reply:trq_01JD5RP"')
    expect(text(mainOf(html))).toContain('Bob replied to your report')
    expect(text(mainOf(html))).toContain('Looking into it.')
    expect(mainOf(html)).toMatch(/<a[^>]*href="\/workflows\?request=trq_01JD5RP"[^>]*>Read the reply<\/a>/)
    expect(navNames(html).filter((name) => name.startsWith('Workflows'))).toEqual([`Workflows, ${needsTotal(HOME)} need you`, `Workflows, ${needsTotal(HOME)} need you`])
  })

  it('leaves a request in Following up but not in Needs you once the person has opened it', () => {
    const opened: HomeOut = { ...HOME, replied: [] }
    const html = mainOf(render({ home: opened }))
    expect(html).not.toContain('reply:trq_01JD5RP')
    expect(html).toContain('data-request="trq_01JD5RP"')
  })
})

describe('a request opened by its link', () => {
  const open = (setup: Setup) => mainOf(render({ home: aliceHome as HomeOut, ...setup, request: { id: 'trq_01JD5RP', ...setup.request } }))

  it('shows the request, who asked, the replies and a reply form to anyone on the team', () => {
    for (const me of [BOB, CAROL]) {
      const html = open({ me, request: { id: 'trq_01JD5RP', data: REQUEST } })
      expect(text(html)).toContain('Alice reported a platform problem')
      expect(text(html)).toContain('It stopped again.')
      expect(text(html)).toContain('Bob')
      expect(text(html)).toContain('Looking into it.')
      expect(html).toContain('href="/runs/run_01JB9"')
      expect(html).toMatch(/<label[^>]*>Your reply<\/label>/)
      expect(html).toMatch(/<button[^>]*>Send reply<\/button>/)
    }
  })

  it('offers someone else Answered, and Done for when nothing more will happen', () => {
    const html = open({ me: BOB, request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).toMatch(/<input[^>]*type="radio"[^>]*checked=""[^>]*\/>Answered/)
    expect(text(html)).toContain('Done, nothing more will happen')
  })

  it('speaks to the asker as you, and offers her only Add and Mark done', () => {
    const html = open({ me: ALICE, request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(text(html)).toContain('You reported a platform problem')
    expect(text(html)).not.toContain('Alice reported')
    expect(text(html)).toContain('Add to your request')
    expect(html).toMatch(/<button[^>]*>Add<\/button>/)
    expect(html).toMatch(/<button[^>]*>Mark done<\/button>/)
    expect(html).not.toContain('type="radio"')
    expect(html).not.toContain('Send reply')
  })

  it('labels the asker’s own note as an addition, never as an answer', () => {
    const noted: TeamRequestView = { ...REQUEST, status: 'open', replies: [{ ...REQUEST.replies[0]!, replied_by: 'alice', replied_by_name: 'Alice', status: 'answered' }] }
    const html = open({ me: BOB, request: { id: 'trq_01JD5RP', data: noted } })
    expect(text(html)).toContain('Added to the request')
    expect(text(html)).not.toMatch(/· Answered/)
  })

  it('replaces the list while it is open, and offers the way back', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).not.toContain('aria-label="Workflows"')
    expect(html).not.toContain('aria-label="Needs you"')
    expect(html).toMatch(/<a[^>]*href="\/workflows"[^>]*>[\s\S]*Workflows<\/a>/)
  })

  it('says plainly when the id is unknown, without a Try again', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: new ApiError(404, null) } })
    expect(text(html)).toContain('There is no request with that link')
    expect(html).not.toContain('Try again')
  })

  it('offers Try again when the platform did not answer', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: new ApiError(503, null) } })
    expect(text(html)).toContain('The request could not be loaded')
    expect(html).toContain('Try again')
  })

  it('says when the card did not reach Teams, and when nobody has replied', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: { ...REQUEST, replies: [], status: 'open', posted_to_teams: false, not_posted_because: 'no_channel' } } })
    expect(text(html)).toContain('Nobody has replied yet.')
    expect(text(html)).toContain('No Teams channel is set up')
  })

  it('has nothing on it that approves', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).not.toMatch(/Approve|Decline|Review and decide/)
  })
})
