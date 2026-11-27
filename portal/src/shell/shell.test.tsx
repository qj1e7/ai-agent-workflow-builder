import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../contracts/fixtures/builder/home.bob.json'
import { App } from '../App'
import { ApiError } from '../api/client'
import { ApiProvider } from '../api/context'
import { TicketLinksProvider } from '../api/ticketLinks'
import { createDevSession, SIGNED_IN, type Session } from '../api/session'
import type { HomeOut, Me, WatchlistView } from '../api/types'
import { howItWorksPath } from '../screens/agents/agents'
import { needsTotal } from '../screens/home/home'
import { focusMovedOutside } from './PersonChip'
import { TEAMS_TITLE } from './TeamsPanel'
import { TEST_NOTE } from './TestControls'
import { oldAgentsDestination, oldExplainDestination, PAGES, railCountFor, railCurrent, railNameFor, RAIL_PAGE_IDS, softwareDestination } from './routes'

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
  readonly now?: Date
}

function render({ path = '/', me = ALICE, meError, oidc = false, browseUrl = null, home, watchlist, now = MORNING }: Setup = {}): string {
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
            <App now={() => now} />
          </MemoryRouter>
        </TicketLinksProvider>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const headings = (html: string) => [...html.matchAll(/<h1\b[^>]*>(.*?)<\/h1>/g)].map((match) => text(match[1] ?? ''))
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const railOf = (html: string) => /<nav\b[^>]*aria-label="Browse"[\s\S]*?<\/nav>/.exec(html)?.[0] ?? ''
const footOf = (html: string) => /<div class="[^"]*foot[^"]*">[\s\S]*?<\/nav>/.exec(railOf(html))?.[0] ?? ''

function currentLinks(html: string): string[] {
  return [...html.matchAll(/<a\b[^>]*>/g)]
    .map((match) => match[0])
    .filter((tag) => tag.includes('aria-current="page"'))
    .map((tag) => /href="([^"]*)"/.exec(tag)?.[1] ?? '')
}

/** The pages the rail leads to, which sit above its foot. */
function railLabels(html: string): string[] {
  const items = /<ul\b[^>]*>([\s\S]*?)<\/ul>/.exec(railOf(html))?.[1] ?? ''
  return [...items.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)].map((match) => text(match[1] ?? ''))
}

const DRAWN_AT_ONCE = RAIL_PAGE_IDS

describe('the rail', () => {
  it('reads Home and Workflows for an Operator, with no Watchlist of its own, no top bar and no Agent library', () => {
    const html = render()
    expect(railLabels(html)).toEqual(['Home', 'Workflows'])
    expect(html).not.toContain('href="/agents"')
    expect(html).not.toContain('<header')
  })

  it('has the same two items for an Approver who is not an Operator', () => {
    const html = render({ me: BOB })
    expect(railLabels(html)).toEqual(['Home', 'Workflows'])
    expect(html).not.toContain('href="/new"')
    expect(html).not.toContain('href="/agents"')
  })

  it('is one nav, with no second tab bar', () => {
    const navs = [...render().matchAll(/<nav\b[^>]*aria-label="Browse"/g)]
    expect(navs).toHaveLength(1)
  })

  it('sends an old /new address, a saved draft’s old link and the old done page to Home, never to a blank page', () => {
    for (const path of ['/new', '/new?draft=drf-1', '/new/done/uc_1']) {
      const html = render({ path })
      expect(html, path).toContain('<main')
      expect(text(mainOf(html)), path).not.toContain('Page not found')
    }
  })

  it('sends an old Explain address to the workflow’s page, which EXPLAIN-gone follows in the browser', () => {
    expect(oldExplainDestination('uc_1')).toBe('/workflows/uc_1')
    expect(oldExplainDestination('uc a')).toBe('/workflows/uc%20a')
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
    expect(heading[0]).toBe(id === 'home' ? 'What can I help you with today?' : railLabel)
    expect(new Set(currentLinks(html))).toEqual(new Set([path]))
  })

  it('keeps Home current only at Home, and an item current on the addresses under it', () => {
    expect(currentLinks(render({ path: '/' }))).toEqual(['/'])
    expect(currentLinks(render({ path: '/workflows/uc_01JB7' }))).toEqual(['/workflows'])
  })

  it('marks Workflows current on a run page and an approval page, whichever workflow the run is', () => {
    expect(currentLinks(render({ path: '/runs/run_01JB8' }))).toEqual(['/workflows'])
    expect(currentLinks(render({ path: '/approvals/apr_01JB8' }))).toEqual(['/workflows'])
    expect(railCurrent('/runs/run_01JB8')).toBe('workflows')
    expect(railCurrent('/workflows')).toBe('workflows')
    expect(railCurrent('/settings')).toBeNull()
  })

  it('sends /software and any address under it to the watchlist’s workflow page, or to Workflows when there is none', () => {
    expect(softwareDestination('/software', 'uc_wl')).toBe('/workflows/uc_wl')
    expect(softwareDestination('/software/', 'uc_wl')).toBe('/workflows/uc_wl')
    expect(softwareDestination('/software/sw_1', 'uc_wl')).toBe('/workflows/uc_wl?software=sw_1')
    expect(softwareDestination('/software/a%20b', 'uc_wl')).toBe('/workflows/uc_wl?software=a+b')
    expect(softwareDestination('/software', 'uc_wl', '?row=sw_2')).toBe('/workflows/uc_wl?software=sw_2')
    expect(softwareDestination('/software', 'uc_wl', '?view=n8n')).toBe('/workflows/uc_wl?view=n8n')
    expect(softwareDestination('/software', null)).toBe('/workflows')
    expect(softwareDestination('/software/sw_1', null)).toBe('/workflows')
  })

  it('marks nothing current for a path the rail does not name', () => {
    expect(currentLinks(render({ path: '/nowhere' }))).toEqual([])
  })
})

const ALICE_HOME = aliceHome as HomeOut
const BOB_HOME: HomeOut = { ...(bobHome as HomeOut), setup_approvals: [] }
const plain = (html: string) => html.replace(/<[^>]*>/g, '')
const linkNames = (html: string) => {
  const items = /<ul\b[^>]*>([\s\S]*?)<\/ul>/.exec(railOf(html))?.[1] ?? ''
  return [...items.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].map((match) => /aria-label="([^"]*)"/.exec(match[1] ?? '')?.[1] ?? plain(match[2] ?? ''))
}


describe('the rail’s counts', () => {
  const needs = needsTotal(ALICE_HOME)

  it('are Home’s Needs you count, and Workflows’ total, in each link’s name', () => {
    const html = render({ home: ALICE_HOME })
    expect(linkNames(html)).toEqual([`Home, ${String(needs)} things need you`, `Workflows, ${String(ALICE_HOME.workflows)} in all`])
  })

  it('turn Home’s count red while anything needs the person, and leave Workflows’ quiet', () => {
    const html = railOf(render({ home: ALICE_HOME }))
    expect(html.match(/data-tone="alert"/g)).toHaveLength(1)
    expect(/<a\b[^>]*aria-label="Home, [^"]*"[\s\S]*?data-tone="alert"[\s\S]*?<\/a>/.test(html)).toBe(true)
  })

  it('are the same numbers an Approver who is not an Operator reads on their Home', () => {
    const html = render({ me: BOB, home: BOB_HOME })
    expect(linkNames(html)).toEqual([`Home, ${String(needsTotal(BOB_HOME))} things need you`, `Workflows, ${String(BOB_HOME.workflows)} in all`])
  })

  it('start the link’s name with its visible label, and show the number once', () => {
    const html = render({ home: ALICE_HOME })
    expect(html.match(/<a\b[^>]*aria-label="Workflows, 1 in all"/g)).toHaveLength(1)
    expect(plain(railOf(html))).toContain('Workflows1')
  })

  it('show nothing for none, or before the numbers have loaded', () => {
    expect(linkNames(render({ home: { ...ALICE_HOME, workflows: 0, setup_approvals: [], approvals_total: 0 } })).filter((name) => name.startsWith('Workflows'))).toEqual(['Workflows'])
    expect(linkNames(render())).toEqual(['Home', 'Workflows'])
  })

  it('leave a calm Home with no count and no red mark', () => {
    const calm: HomeOut = { ...ALICE_HOME, approvals_total: 0, confirmations: [], setup_approvals: [], stopped_total: 0, fixes: [], declined_total: 0, questions_for_me_total: 0, connections: [], addresses: [], replied: [] }
    expect(needsTotal(calm)).toBe(0)
    const html = railOf(render({ home: calm }))
    expect(html).not.toContain('data-tone="alert"')
    expect(linkNames(render({ home: calm }))[0]).toBe('Home')
  })

  it('follow one rule for every item', () => {
    expect(railCountFor('home', { needs: 3, workflows: 5 })).toBe(3)
    expect(railCountFor('home', { needs: 0, workflows: 5 })).toBeNull()
    expect(railCountFor('workflows', { needs: 3, workflows: 5 })).toBe(5)
    expect(railCountFor('workflows', { workflows: 0 })).toBeNull()
    expect(railCountFor('workflows', {})).toBeNull()
    expect(railNameFor('home', 1)).toBe('Home, 1 thing needs you')
    expect(railNameFor('workflows', 4)).toBe('Workflows, 4 in all')
    expect(railNameFor('home', null)).toBeUndefined()
  })
})

describe('Settings at the rail’s foot', () => {
  it('is a link to /settings and, there, shows the Settings heading with the link marked current', () => {
    const html = render()
    expect(footOf(html)).toMatch(/<a\b[^>]*href="\/settings"[^>]*>/)
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

  it('open Home with the greeting in Singapore time, as a line above the heading', () => {
    const main = text(mainOf(render({ home: ALICE_HOME })))
    expect(main).toContain('Good morning, Alice What can I help you with today?')
  })

  it('greet Alice and give Home’s times in the team time zone /api/v1/me names', () => {
    const evening = new Date('2026-10-28T20:00:00Z')
    const london = text(mainOf(render({ home: ALICE_HOME, me: { ...ALICE, time_zone: 'Europe/London' }, now: evening })))
    expect(london).toContain('Good evening, Alice')
    expect(london).toContain('Software watchlist stopped Wed 4 Nov at 2:14')
    const singapore = text(mainOf(render({ home: ALICE_HOME, now: evening })))
    expect(singapore, 'an answer that names no zone is Singapore’s').toContain('Good morning, Alice')
    expect(singapore).toContain('Software watchlist stopped Wed 4 Nov at 10:14')
  })

  it('never use the retired names', () => {
    for (const path of ['/', '/workflows', '/software', '/settings', '/settings?tab=how', '/nowhere']) {
      expect(text(render({ path })), path).not.toMatch(/room lead|release checker|use case/i)
    }
  })
})

describe('the person', () => {
  it('shows the signed-in person as “Name, Role” beside their initial, as the sketch does', () => {
    const header = railOf(render())
    expect(text(header)).toContain('A Alice, Operator and Approver')
    expect(header).toMatch(/aria-hidden="true"[^>]*>A<\/span>/)
  })

  it('adds n8n access for someone who has it, as the sketch’s “Alice, Operator, n8n access”', () => {
    expect(text(railOf(render({ me: { id: 'alice', display: 'Alice', roles: ['operator'], n8n_access: true } })))).toContain('Alice, Operator, n8n access')
    expect(text(railOf(render()))).not.toContain('n8n access')
  })

  it('shows Bob as an Approver', () => {
    expect(text(railOf(render({ me: BOB })))).toContain('Bob, Approver')
    expect(text(railOf(render({ me: BOB })))).not.toContain('Operator')
  })

  it('is a button with the dev sign-in too, so a keyboard or a touch can read who they are, with no Sign out', () => {
    const html = railOf(render())
    expect(html).toMatch(/<button\b[^>]*aria-expanded="false"[^>]*>/)
    expect(html).not.toContain('Sign out')
  })

  it('is a collapsed button with real sign-in, and Sign out is not shown yet', () => {
    const header = railOf(render({ oidc: true }))
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
  it('puts the skip link before the rail', () => {
    const html = render()
    expect(html.indexOf('Skip to main content')).toBeGreaterThanOrEqual(0)
    expect(html.indexOf('Skip to main content')).toBeLessThan(html.indexOf('<nav'))
  })

  it('puts the AI mark at the rail’s top, named for the product', () => {
    expect(railOf(render())).toContain('aria-label="AI Workflow Builder"')
  })
})

describe('when the platform is down', () => {
  it.each([
    ['a network failure', new TypeError('Failed to fetch')],
    ['a 502', new ApiError(502, null)],
    ['a 500', new ApiError(500, null)],
  ])('after %s, still shows the rail and says it cannot reach the platform', (_name, meError) => {
    const html = render({ meError })
    expect(headings(html)).toEqual(["We can't reach the platform"])
    expect(text(mainOf(html))).toContain('Check your connection, or try again in a moment.')
    expect(mainOf(html)).toMatch(/<button\b[^>]*>Try again<\/button>/)
    expect(railOf(html)).toContain('aria-label="AI Workflow Builder"')
    expect(railLabels(html)).toEqual(['Home', 'Workflows'])
    expect(railOf(html)).not.toContain('Operator')
  })

  it('does not say so for a refusal below 500', () => {
    const html = render({ meError: new ApiError(403, null), home: BOB_HOME })
    expect(headings(html)).toEqual(['3 things need you'])
    expect(text(mainOf(html))).toContain('Good morning 3 things need you')
  })

  it('keeps the test controls, so a stale person can be swapped', () => {
    expect(render({ meError: new ApiError(401, null) })).toContain('Test controls')
  })
})

describe('the way in to the practice Jira', () => {
  const jiraLink = /<a\b[^>]*aria-label="Jira, practice copy"[^>]*href="\/jira"[^>]*>[\s\S]*?<\/a>/

  it('is a link at the rail’s foot, next to Teams and Settings, with a visible Jira label, and not among its pages', () => {
    const html = render()
    const link = jiraLink.exec(footOf(html))?.[0] ?? ''
    expect(text(link)).toBe('Jira')
    expect(railLabels(html)).not.toContain('Practice Jira')
  })

  it('is left out for someone who is not on the People list, as Teams is', () => {
    const mallory: Me = { id: 'mallory', display: 'Mallory', roles: [], on_list: false }
    expect(railOf(render({ me: mallory }))).not.toContain('href="/jira"')
  })

  it('is left out when a real Jira address is configured, because the page has nothing to show then', () => {
    expect(railOf(render({ browseUrl: 'https://jira.example.test/browse/{key}' }))).not.toContain('href="/jira"')
  })

  it('shows the practice Jira page at /jira/KEY with its own heading, loaded on demand', () => {
    const html = render({ path: '/jira/OPS-1' })
    expect(headings(html)).toEqual(['Practice Jira'])
    expect(text(mainOf(html))).toContain('Loading')
  })
})
