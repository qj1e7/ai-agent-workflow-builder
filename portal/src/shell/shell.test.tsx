import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../contracts/fixtures/builder/home.bob.json'
import movedWatchlist from '../../../contracts/fixtures/watchlist/moved.json'
import statusesWatchlist from '../../../contracts/fixtures/watchlist/statuses.json'
import { App } from '../App'
import { ApiError } from '../api/client'
import { ApiProvider } from '../api/context'
import { TicketLinksProvider } from '../api/ticketLinks'
import { createDevSession, SIGNED_IN, type Session } from '../api/session'
import type { HomeOut, Me, WatchlistView } from '../api/types'
import { howItWorksPath } from '../screens/agents/agents'
import { needsTotal } from '../screens/home/home'
import { watchAttention } from '../screens/software/software'
import { focusMovedOutside } from './PersonChip'
import { TEAMS_TITLE } from './TeamsPanel'
import { TEST_NOTE } from './TestControls'
import { oldAgentsDestination, PAGES, railCountFor, railCurrent, RAIL_PAGE_IDS } from './routes'

const ORIGIN = 'http://portal.test'
const MORNING = new Date('2026-10-29T03:00:00Z')

const ALICE: Me = { id: '0a11ce00-0000-4000-8000-000000000001', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: '0b0b0000-0000-4000-8000-000000000002', display: 'Bob', roles: ['approver'] }

const oidcSession: Session = {
  kind: 'oidc',
  cacheScope: () => 'subject-1',
  status: () => SIGNED_IN,
  subscribe: () => () => undefined,
  credentials: () => Promise.resolve({}),
  refusedByPlatform: () => undefined,
  signIn: () => Promise.resolve(),
  signOut: () => Promise.resolve(),
}

interface Setup {
  readonly path?: string
  readonly me?: Me
  readonly meError?: Error
  readonly oidc?: boolean
  readonly browseUrl?: string | null
  readonly home?: HomeOut
  readonly watchlist?: WatchlistView
}

function render({ path = '/', me = ALICE, meError, oidc = false, browseUrl = null, home, watchlist }: Setup = {}): string {
  const session = oidc ? oidcSession : createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  const key = ['me', session.cacheScope()]
  if (meError === undefined) queryClient.setQueryData(key, me)
  else queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: meError, fetchStatus: 'idle' })
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  if (home) queryClient.setQueryData(['home', session.cacheScope()], home)
  if (watchlist) queryClient.setQueryData(['watchlist', session.cacheScope()], watchlist)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin={ORIGIN}>
        <TicketLinksProvider config={{ jiraBrowseUrl: browseUrl }}>
          <MemoryRouter initialEntries={[path]}>
            <App now={() => MORNING} />
          </MemoryRouter>
        </TicketLinksProvider>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const headings = (html: string) => [...html.matchAll(/<h1\b[^>]*>(.*?)<\/h1>/g)].map((match) => text(match[1] ?? ''))
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const headerOf = (html: string) => /<header\b[\s\S]*<\/header>/.exec(html)?.[0] ?? ''

function currentLinks(html: string): string[] {
  return [...html.matchAll(/<a\b[^>]*>/g)]
    .map((match) => match[0])
    .filter((tag) => tag.includes('aria-current="page"'))
    .map((tag) => /href="([^"]*)"/.exec(tag)?.[1] ?? '')
}

function railLabels(html: string): string[] {
  const nav = /<nav\b[^>]*aria-label="Main"[^>]*>([\s\S]*?)<\/nav>/.exec(html)?.[1] ?? ''
  return [...nav.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)].map((match) => text(match[1] ?? ''))
}

const DRAWN_AT_ONCE = RAIL_PAGE_IDS

describe('the rail', () => {
  it('reads Chat, Workflows and Watchlist for an Operator, with no menu in the header and no Agent library', () => {
    const html = render()
    expect(railLabels(html)).toEqual(['Chat', 'Workflows', 'Watchlist'])
    expect(html).not.toContain('href="/agents"')
    expect(headerOf(html)).not.toMatch(/aria-label="Main"/)
  })

  it('has the same three items for an Approver who is not an Operator', () => {
    const html = render({ me: BOB })
    expect(railLabels(html)).toEqual(['Chat', 'Workflows', 'Watchlist'])
    expect(html).not.toContain('href="/new"')
    expect(html).not.toContain('href="/agents"')
  })

  it('is one nav, with no second tab bar', () => {
    const navs = [...render().matchAll(/<nav\b[^>]*aria-label="Main"/g)]
    expect(navs).toHaveLength(1)
  })

  it('sends an old /new address, a saved draft’s old link and the old done page to Home, never to a blank page', () => {
    for (const path of ['/new', '/new?draft=drf-1', '/new/done/uc_1']) {
      const html = render({ path })
      expect(html, path).toContain('<main')
      expect(text(mainOf(html)), path).not.toContain('Page not found')
    }
  })

  it('sends the old Agent library address to How it works for an Operator, keeping the agent and the tab, and Home for anyone else', () => {
    expect(oldAgentsDestination(true, null, null)).toBe('/settings?tab=how')
    expect(oldAgentsDestination(true, 'crd_version_checker', null)).toBe(howItWorksPath({ show: 'agents', agent: 'crd_version_checker' }))
    expect(oldAgentsDestination(true, 'planner', 'agents')).toBe('/settings?tab=how&show=agents&agent=planner')
    expect(oldAgentsDestination(true, null, 'tools')).toBe('/settings?tab=how&show=tools')
    expect(oldAgentsDestination(false, 'planner', 'agents')).toBe('/')
    expect(render({ path: '/agents/planner' })).toContain('<main')
  })

  it.each(DRAWN_AT_ONCE)('%s links to its path, and at that path shows its own heading with the item marked current', (id) => {
    const { path, railLabel } = PAGES[id]
    const html = render({ path, home: ALICE_HOME })
    expect(html).toContain(`href="${path}"`)
    const heading = headings(html)
    expect(heading).toHaveLength(1)
    expect(heading[0]).toBe(id === 'home' ? 'Good morning! Alice' : railLabel)
    expect(new Set(currentLinks(html))).toEqual(new Set([path]))
  })

  it('keeps Home current only at Home, and an item current on the addresses under it', () => {
    expect(currentLinks(render({ path: '/' }))).toEqual(['/'])
    expect(currentLinks(render({ path: '/workflows/uc_01JB7' }))).toEqual(['/workflows'])
    expect(currentLinks(render({ path: '/software/anything' }))).toEqual(['/software'])
  })

  it('marks Workflows current on a run page and an approval page, and Watchlist when the run is the watchlist’s', () => {
    expect(currentLinks(render({ path: '/runs/run_01JB8' }))).toEqual(['/workflows'])
    expect(currentLinks(render({ path: '/approvals/apr_01JB8' }))).toEqual(['/workflows'])
    expect(railCurrent('/runs/run_01JB8', 'software')).toBe('software')
    expect(railCurrent('/approvals/apr_01JB8', 'software')).toBe('software')
    expect(railCurrent('/runs/run_01JB8', 'workflows')).toBe('workflows')
    expect(railCurrent('/workflows', 'software')).toBe('workflows')
    expect(railCurrent('/settings', 'workflows')).toBeNull()
  })

  it('marks nothing current for a path the rail does not name', () => {
    expect(currentLinks(render({ path: '/nowhere' }))).toEqual([])
  })
})

const ALICE_HOME = aliceHome as HomeOut
const BOB_HOME = bobHome as HomeOut
const plain = (html: string) => html.replace(/<[^>]*>/g, '')
const linkNames = (html: string) =>
  [...html.matchAll(/<nav\b[^>]*aria-label="Main"[^>]*>([\s\S]*?)<\/nav>/g)].flatMap((nav) =>
    [...(nav[1] ?? '').matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].map((match) => /aria-label="([^"]*)"/.exec(match[1] ?? '')?.[1] ?? plain(match[2] ?? '')),
  )

const SOFTWARE_WITH_DECISION = statusesWatchlist as WatchlistView
const SOFTWARE_WITH_ADDRESSES = movedWatchlist as WatchlistView

describe('the rail’s counts', () => {
  it('shows needsTotal on Workflows for an Operator, in the link’s name', () => {
    const total = needsTotal(ALICE_HOME)
    expect(total).toBeGreaterThan(0)
    const html = render({ home: ALICE_HOME })
    expect(linkNames(html).filter((name) => name.startsWith('Workflows'))).toEqual([`Workflows, ${total} need you`])
    expect(linkNames(html).filter((name) => name.startsWith('Chat'))).toEqual(['Chat'])
  })

  it('shows it on Chat instead for an Approver who is not an Operator', () => {
    const total = needsTotal(BOB_HOME)
    const html = render({ me: BOB, home: BOB_HOME })
    expect(linkNames(html).filter((name) => name.includes('need you'))).toEqual([`Chat, ${total} need you`])
    expect(linkNames(html)).toContain('Workflows')
  })

  it('starts the link’s name with its visible label, and shows the number once', () => {
    const html = render({ home: ALICE_HOME })
    const total = needsTotal(ALICE_HOME)
    expect(html.match(new RegExp(`<a\\b[^>]*aria-label="Workflows, ${total} need you"`, 'g'))).toHaveLength(1)
    expect(plain(html.match(/<nav\b[^>]*aria-label="Main"[\s\S]*?<\/nav>/)?.[0] ?? '')).toContain(`Workflows${total}`)
  })

  it('shows no count when nothing needs the person, or before Home has loaded', () => {
    const quiet: HomeOut = { ...ALICE_HOME, approvals: [], approvals_total: 0, confirmations: [], stopped: [], stopped_total: 0, replied: [], connections: [], addresses: [] }
    expect(linkNames(render({ home: quiet })).some((name) => name.includes('need you'))).toBe(false)
    expect(linkNames(render()).some((name) => name.includes('need you'))).toBe(false)
  })

  it('shows what needs action on the Watchlist for an Operator, the number the Software page counts under Needs attention', () => {
    for (const watchlist of [SOFTWARE_WITH_DECISION, SOFTWARE_WITH_ADDRESSES]) {
      const total = watchAttention(watchlist.software)
      expect(total).toBeGreaterThan(0)
      const html = render({ home: ALICE_HOME, watchlist })
      expect(linkNames(html).filter((name) => name.startsWith('Watchlist'))).toEqual([`Watchlist, ${total} need action`])
    }
  })

  it('gives an Approver who is not an Operator no Watchlist count, whatever the list holds', () => {
    const html = render({ me: BOB, home: BOB_HOME, watchlist: SOFTWARE_WITH_DECISION })
    expect(linkNames(html).filter((name) => name.startsWith('Watchlist'))).toEqual(['Watchlist'])
  })

  it('has no Watchlist count when nothing on the list needs action', () => {
    expect(linkNames(render({ home: ALICE_HOME })).filter((name) => name.startsWith('Watchlist'))).toEqual(['Watchlist'])
  })

  it('follows one rule for who sees which count', () => {
    expect(railCountFor('workflows', true, 5, 2)).toEqual({ total: 5, says: 'need you' })
    expect(railCountFor('home', true, 5, 2)).toBeNull()
    expect(railCountFor('home', false, 5, 2)).toEqual({ total: 5, says: 'need you' })
    expect(railCountFor('workflows', false, 5, 2)).toBeNull()
    expect(railCountFor('software', true, 5, 2)).toEqual({ total: 2, says: 'need action' })
    expect(railCountFor('software', false, 5, 2)).toBeNull()
    expect(railCountFor('workflows', true, 0, 0)).toBeNull()
  })
})

describe('the Settings gear', () => {
  it('links to /settings and, there, shows the Settings heading with the gear marked current', () => {
    const html = render()
    expect(html).toMatch(/<a\b[^>]*aria-label="Settings"[^>]*href="\/settings"|<a\b[^>]*href="\/settings"[^>]*aria-label="Settings"/)
    const settings = render({ path: '/settings' })
    expect(headings(settings)).toEqual(['Settings'])
    expect(currentLinks(settings)).toEqual(['/settings'])
  })

  it('opens for an Approver who is not an Operator', () => {
    expect(headings(render({ path: '/settings', me: BOB }))).toEqual(['Settings'])
  })
})

describe('an unknown path', () => {
  it('says Page not found and offers Home', () => {
    const html = render({ path: '/nowhere/abc' })
    expect(headings(html)).toEqual(['Page not found'])
    expect(mainOf(html)).toMatch(/<a\b[^>]*href="\/"[^>]*>Go to Home<\/a>/)
  })
})

describe('a run or an approval link', () => {
  it.each(['/runs/run_01JB8', '/approvals/apr_01JB8'])('%s opens the run page, which loads on demand', (path) => {
    const html = render({ path })
    expect(headings(html)).toEqual([])
    expect(text(mainOf(html))).toBe('Loading')
    expect(currentLinks(html)).toEqual(['/workflows'])
  })
})

describe('the pages', () => {
  it('give every heading a tabindex so focus can move to it', () => {
    for (const path of [...DRAWN_AT_ONCE.map((id) => PAGES[id].path), '/settings', '/nowhere']) {
      const tags = [...render({ path, home: ALICE_HOME }).matchAll(/<h1\b[^>]*>/g)]
      expect(tags.length, path).toBeGreaterThan(0)
      expect(tags.every((tag) => tag[0].includes('tabindex="-1"')), path).toBe(true)
    }
  })

  it('open Home with the greeting and today in Singapore time', () => {
    const main = text(mainOf(render({ home: ALICE_HOME })))
    expect(main).toContain('Good morning! Alice')
  })

  it('never use the retired names', () => {
    for (const path of ['/', '/workflows', '/software', '/settings', '/settings?tab=how', '/nowhere']) {
      expect(text(render({ path })), path).not.toMatch(/room lead|release checker|use case/i)
    }
  })
})

describe('the person', () => {
  it('shows the signed-in name, initial and roles in the header', () => {
    const header = headerOf(render())
    expect(text(header)).toContain('Alice')
    expect(text(header)).toContain('Operator and Approver')
    expect(header).toMatch(/aria-hidden="true"[^>]*>A<\/span>/)
  })

  it('shows Bob as an Approver', () => {
    expect(text(headerOf(render({ me: BOB })))).toContain('Approver')
    expect(text(headerOf(render({ me: BOB })))).not.toContain('Operator')
  })

  it('is not a control with the dev sign-in', () => {
    expect(headerOf(render())).not.toContain('aria-expanded')
  })

  it('is a collapsed button with real sign-in, and Sign out is not shown yet', () => {
    const header = headerOf(render({ oidc: true }))
    expect(header).toMatch(/<button\b[^>]*aria-expanded="false"[^>]*>/)
    expect(header).not.toContain('Sign out')
  })
})

describe('the person chip panel', () => {
  const root = { contains: (node: unknown) => node === 'inside' } as unknown as Pick<Node, 'contains'>

  it('stays open when focus is lost with no target, as Safari does on a press of Sign out', () => {
    expect(focusMovedOutside(root, null)).toBe(false)
  })

  it('stays open when focus moves inside', () => {
    expect(focusMovedOutside(root, 'inside' as unknown as EventTarget)).toBe(false)
  })

  it('closes when focus moves to an element outside', () => {
    expect(focusMovedOutside(root, 'outside' as unknown as EventTarget)).toBe(true)
  })
})

describe('the test controls', () => {
  it('are offered with the dev sign-in', () => {
    expect(render()).toContain('Test controls')
  })

  it('are not offered with real sign-in', () => {
    const html = render({ oidc: true })
    expect(html).not.toContain('Test controls')
    expect(html).not.toContain(TEST_NOTE)
  })
})

describe('the Teams button', () => {
  it('is named the practice copy, and its panel is a dialog of the same name that stays empty until opened', () => {
    const html = render()
    expect(html).toMatch(new RegExp(`<button\\b[^>]*aria-label="${TEAMS_TITLE}"`))
    expect(html).toMatch(new RegExp(`<dialog\\b[^>]*aria-label="${TEAMS_TITLE}"`))
    expect(text(/<dialog\b[\s\S]*?<\/dialog>/.exec(html)?.[0] ?? '')).toBe('')
  })
})

describe('the frame', () => {
  it('puts the skip link before the header', () => {
    const html = render()
    expect(html.indexOf('Skip to main content')).toBeGreaterThanOrEqual(0)
    expect(html.indexOf('Skip to main content')).toBeLessThan(html.indexOf('<header'))
  })

  it('names the product in the header', () => {
    expect(text(headerOf(render()))).toContain('AI Workflow Builder')
  })
})

describe('when the platform is down', () => {
  it.each([
    ['a network failure', new TypeError('Failed to fetch')],
    ['a 502', new ApiError(502, null)],
    ['a 500', new ApiError(500, null)],
  ])('after %s, still shows the header and says it cannot reach the platform', (_name, meError) => {
    const html = render({ meError })
    expect(headings(html)).toEqual(["We can't reach the platform"])
    expect(text(mainOf(html))).toContain('Check your connection, or try again in a moment.')
    expect(mainOf(html)).toMatch(/<button\b[^>]*>Try again<\/button>/)
    expect(text(headerOf(html))).toContain('Workflow Builder')
    expect(railLabels(html)).toEqual(['Chat', 'Workflows', 'Watchlist'])
    expect(headerOf(html)).not.toContain('Operator')
  })

  it('does not say so for a refusal below 500', () => {
    expect(headings(render({ meError: new ApiError(403, null), home: BOB_HOME }))).toEqual(['Good morning'])
  })

  it('keeps the test controls, so a stale person can be swapped', () => {
    expect(render({ meError: new ApiError(401, null) })).toContain('Test controls')
  })
})

describe('the way in to the practice Jira', () => {
  const jiraLink = /<a\b[^>]*aria-label="Jira, practice copy"[^>]*href="\/jira"[^>]*>[\s\S]*?<\/a>/

  it('is a header link next to Teams and Settings, with a visible Jira label, and not in the rail', () => {
    const html = render()
    const link = jiraLink.exec(headerOf(html))?.[0] ?? ''
    expect(text(link)).toBe('Jira')
    expect(railLabels(html)).not.toContain('Practice Jira')
  })

  it('is left out for someone who is not on the People list, as Teams is', () => {
    const mallory: Me = { id: 'mallory', display: 'Mallory', roles: [], on_list: false }
    expect(headerOf(render({ me: mallory }))).not.toContain('href="/jira"')
  })

  it('is left out when a real Jira address is configured, because the page has nothing to show then', () => {
    expect(headerOf(render({ browseUrl: 'https://jira.example.test/browse/{key}' }))).not.toContain('href="/jira"')
  })

  it('shows the practice Jira page at /jira/KEY with its own heading, loaded on demand', () => {
    const html = render({ path: '/jira/OPS-1' })
    expect(headings(html)).toEqual(['Practice Jira'])
    expect(text(mainOf(html))).toContain('Loading')
  })
})
