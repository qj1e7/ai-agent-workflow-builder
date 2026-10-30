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
import type { Me, RunView, UseCaseView } from '../../api/types'

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
}

function render({ me = ALICE, useCases = [BUGS, WATCHLIST, LANGGRAPH], runs = RUNS, state }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB, CAROL])
  queryClient.setQueryData(['runs', scope], runs)
  if (useCases instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['use-cases', scope] }).setState({ status: 'error', error: useCases, fetchStatus: 'idle' })
  else if (useCases !== 'loading') queryClient.setQueryData(['use-cases', scope], useCases)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[{ pathname: '/workflows', state }]}>
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
    expect(text(bugs)).toContain('Today 10:14: stopped. An agent could not finish its work.')
    const watchlist = rowOf(html, 'uc_01JB7')
    expect(watchlist).toMatch(/data-tone="wait"[^>]*>.*Needs a yes<\/span>/)
    expect(text(watchlist)).toContain('Tue 3 Nov: 1 ticket is waiting for a yes.')
    const paused = rowOf(html, 'uc_lang')
    expect(paused).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
    expect(text(paused)).toContain('No runs yet.')
  })

  it('shows the next run beside it: a date, Paused, or Not scheduled', () => {
    const html = render()
    expect(text(rowOf(html, 'uc_01JB7'))).toContain('Next: Mon 9 Nov, 9:00')
    expect(text(rowOf(html, 'uc_lang'))).toContain('Next: Paused')
    expect(text(rowOf(html, 'uc_bugs'))).toContain('Not scheduled')
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

  it('closes the faces of a paused workflow and marks the agent whose work waits', () => {
    const html = render()
    expect(rowOf(html, 'uc_lang')).not.toMatch(/data-state="(idle|waiting)"/)
    expect(rowOf(html, 'uc_lang')).toContain('data-state="stopped"')
    expect(rowOf(html, 'uc_01JB7')).toContain('data-state="waiting"')
  })

  it('has a search box and the four filters, with All pressed', () => {
    const main = mainOf(render())
    expect(main).toMatch(/<label[^>]*for="find-workflows"[^>]*>Find a workflow<\/label>/)
    expect(main).toMatch(/<input[^>]*type="search"[^>]*id="find-workflows"|<input[^>]*id="find-workflows"[^>]*type="search"/)
    const pressed = [...main.matchAll(/<button[^>]*aria-pressed="(true|false)"[^>]*>([^<]*)<\/button>/g)].map((m) => [m[2], m[1]])
    expect(pressed).toEqual([
      ['All', 'true'],
      ['Needs you', 'false'],
      ['Stopped', 'false'],
      ['Paused', 'false'],
    ])
  })

  it('looks the same to an Approver apart from the row buttons, and has no change controls', () => {
    const main = text(mainOf(render({ me: BOB })))
    expect(main).toContain('Morning bug report check')
    expect(main).not.toMatch(/\bPause\b|\bResume\b|\bDelete\b|Run now/)
  })

  it('says when there is nothing yet, in words for the person reading', () => {
    expect(text(mainOf(render({ useCases: [] })))).toContain('No workflows yet')
    expect(text(mainOf(render({ useCases: [], me: BOB })))).toContain('An Operator sets them up. You approve their changes.')
    expect(mainOf(render({ useCases: [] }))).not.toContain('find-workflows')
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
