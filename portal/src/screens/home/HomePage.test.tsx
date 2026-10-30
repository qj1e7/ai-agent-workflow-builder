import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import dayOne from '../../../../contracts/fixtures/builder/home.day-one.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ApprovalItem, HomeOut, Me } from '../../api/types'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const ERIN: Me = { id: 'erin', display: 'Erin', roles: ['operator'] }

const BOB_HOME = bobHome as HomeOut
const ALICE_HOME = aliceHome as HomeOut
const DAY_ONE = dayOne as HomeOut
const NOW = new Date('2026-11-03T15:00:00+08:00')

function render(me: Me, home: HomeOut | Error | 'loading'): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  if (home instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['home', scope] }).setState({ status: 'error', error: home, fetchStatus: 'idle' })
  else if (home !== 'loading') queryClient.setQueryData(['home', scope], home)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={['/']}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
function itemOf(html: string, key: string): string {
  const start = html.indexOf(`data-home-item="${key}"`)
  if (start < 0) return ''
  const rest = html.slice(start)
  const end = rest.slice(1).search(/<li[^>]*data-home-item=|<\/section>/)
  return end < 0 ? rest : rest.slice(0, end + 1)
}
const sectionOf = (html: string, heading: string) => new RegExp(`<section[^>]*>\\s*<h2[^>]*>${heading}[\\s\\S]*?</section>`).exec(html)?.[0] ?? ''
const linksIn = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [text(m[2] ?? ''), m[1]])
const buttonsIn = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const primaries = (html: string) => (html.match(/class="[^"]*_primary_[^"]*"/g) ?? []).length

describe('Home for an Approver with a run waiting for his yes', () => {
  const html = mainOf(render(BOB, BOB_HOME))

  it('says how many things need him under the greeting, and what runs next', () => {
    expect(text(html)).toContain('Good afternoon, Bob Tuesday 3 November. 3 things need you. Everything else is running.')
    expect(text(html)).toContain('Coming up next: Software watchlist , Mon 9 Nov, 9:00.')
    expect(linksIn(html)).toContainEqual(['Software watchlist', '/software'])
    expect(linksIn(html)).toContainEqual(['See all workflows', '/workflows'])
  })

  it('puts the waiting run first, as the card with the one main button, which opens the run at the decision', () => {
    const first = /<ul[^>]*aria-label="Needs you"[^>]*>\s*<li[^>]*data-home-item="([^"]+)"/.exec(html)?.[1]
    expect(first).toBe('approval:apr_01JB8')
    const card = itemOf(html, 'approval:apr_01JB8')
    expect(text(card)).toContain('1 ticket is waiting for your yes')
    expect(text(card)).toContain('Software watchlist · Started by Alice, Today, 10:14')
    expect(text(card)).toContain('Upgrade LangGraph from 1.2.14 to 1.2.16')
    expect(linksIn(card)).toEqual([['Review and decide', '/runs/run_01JB8']])
    expect(primaries(card)).toBe(1)
    expect(primaries(html)).toBe(1)
  })

  it('lists the confirmations as rows that open Settings', () => {
    expect(text(itemOf(html, 'confirmation:cfm_01JD4VE'))).toContain('Confirm Dave as an Approver')
    expect(linksIn(itemOf(html, 'confirmation:cfm_01JD4VE'))).toEqual([['Review in Settings', '/settings?tab=people']])
    expect(linksIn(itemOf(html, 'confirmation:cfm_01JADDR'))).toEqual([['Review in Settings', '/settings']])
  })

  it('never offers a decision on Home', () => {
    expect([...buttonsIn(html), ...linksIn(html).map(([name]) => name)].filter((name) => /^(Approve|Decline|Confirm|Not now)/.test(name ?? ''))).toEqual([])
  })

  it('has nothing for him under Waiting on others or Your drafts, and offers How it works as a link', () => {
    expect(html).not.toContain('Waiting on others')
    expect(html).not.toContain('Your drafts')
    expect(buttonsIn(html)).toContain('How it works')
  })
})

describe('Home for the Operator who started that run', () => {
  const html = mainOf(render(ALICE, ALICE_HOME))

  it('shows her stopped run with the AI troubleshooter’s reason, a retry, and the run', () => {
    const card = itemOf(html, 'stopped:run_01JB9')
    expect(text(card)).toContain('Software watchlist stopped')
    expect(text(card)).toContain('AI troubleshooter An agent could not finish its work. Retry the run. If it fails again, check whether that service is up.')
    expect(buttonsIn(card)).toEqual(['Retry the run'])
    expect(linksIn(card)).toEqual([['See the run', '/runs/run_01JB9']])
  })

  it('shows the run waiting for someone else’s yes under Waiting on others, with no Approve button', () => {
    const waiting = sectionOf(html, 'Waiting on others')
    expect(linksIn(waiting)).toEqual([['An Approver’s yes on Software watchlist You started it · Today 10:14', '/runs/run_01JB8']])
    expect(buttonsIn(waiting)).toEqual([])
  })

  it('lists her draft by name, with its step and when it was saved', () => {
    const drafts = sectionOf(html, 'Your drafts')
    expect(text(drafts)).toContain('Nudge stale tickets Step 2 of 4. Last saved Wed 4 Nov, 14:24.')
  })
})

describe('Home on day one', () => {
  const html = mainOf(render(ERIN, DAY_ONE))

  it('says nothing needs you yet, that all is quiet, and how it works', () => {
    expect(text(html)).toContain('Tuesday 3 November. Nothing needs you yet. When a workflow wants to change something, it shows up here and in Teams.')
    expect(text(sectionOf(html, 'Needs you'))).toContain('All quiet Nothing is scheduled yet.')
    const how = sectionOf(html, 'How it works')
    expect([...how.matchAll(/<li>/g)]).toHaveLength(4)
    expect(text(how)).toContain('Say yes in Teams Nothing changes in Jira or Confluence until an Approver agrees.')
    expect(buttonsIn(html)).not.toContain('How it works')
  })
})

describe('Home with nothing to do on a team with workflows', () => {
  it('says nothing needs you right now and names what runs next', () => {
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals: [], approvals_total: 0, confirmations: [] }))
    expect(text(html)).toContain('Nothing needs you right now. Your workflows are running.')
    expect(text(html)).toContain('All quiet Next up: Software watchlist , Mon 9 Nov, 9:00.')
    expect(html).not.toContain('Coming up next')
  })
})

describe('Home with many runs waiting', () => {
  it('shows the newest ten and says how many more are waiting', () => {
    const [ask] = BOB_HOME.approvals as [ApprovalItem]
    const approvals = Array.from({ length: 10 }, (_, n) => ({ ...ask, run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:${String(n).padStart(2, '0')}:00Z` }))
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals, approvals_total: 50, confirmations: [] }))
    expect([...html.matchAll(/data-home-item=/g)]).toHaveLength(10)
    expect(/data-home-item="([^"]+)"/.exec(html)?.[1]).toBe('approval:apr_9')
    expect(text(html)).toContain('50 things need you.')
    expect(text(html)).toContain('40 more runs are waiting for your yes.')
  })
})

describe('Home before it knows', () => {
  it('keeps the greeting and says it is loading', () => {
    const html = mainOf(render(BOB, 'loading'))
    expect(text(html)).toContain('Good afternoon, Bob Tuesday 3 November. Loading what needs you')
  })

  it('says it could not load, and offers to try again', () => {
    const html = mainOf(render(BOB, new ApiError(500, null)))
    expect(text(html)).toContain('Home could not be loaded.')
    expect(buttonsIn(html)).toEqual(['Try again'])
  })
})
