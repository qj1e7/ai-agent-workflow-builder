import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
import { ApiError } from '../api/client'
import { ApiProvider } from '../api/context'
import { createDevSession, SIGNED_IN, type Session } from '../api/session'
import type { Me } from '../api/types'
import { focusMovedOutside } from './PersonChip'
import { TEAMS_TITLE } from './TeamsPanel'
import { TEST_NOTE } from './TestControls'
import { MENU_PAGE_IDS, PAGES } from './routes'

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
}

function render({ path = '/', me = ALICE, meError, oidc = false }: Setup = {}): string {
  const session = oidc ? oidcSession : createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  const key = ['me', session.cacheScope()]
  if (meError === undefined) queryClient.setQueryData(key, me)
  else queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: meError, fetchStatus: 'idle' })
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin={ORIGIN}>
        <MemoryRouter initialEntries={[path]}>
          <App now={() => MORNING} />
        </MemoryRouter>
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

function menuLabels(html: string): string[] {
  const nav = /<nav\b[^>]*aria-label="Main"[^>]*>([\s\S]*?)<\/nav>/.exec(html)?.[1] ?? ''
  return [...nav.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)].map((match) => text(match[1] ?? ''))
}

describe('the menu', () => {
  it('reads Home, Workflows, Software watchlist, Agent library', () => {
    expect(menuLabels(render())).toEqual(['Home', 'Workflows', 'Software watchlist', 'Agent library'])
  })

  it('has the same four items on the phone tab bar', () => {
    const html = render()
    const bars = [...html.matchAll(/<nav\b[^>]*aria-label="Main"[^>]*>([\s\S]*?)<\/nav>/g)].map((match) =>
      [...(match[1] ?? '').matchAll(/<a\b[^>]*href="([^"]*)"/g)].map((link) => link[1]),
    )
    expect(bars).toHaveLength(2)
    expect(bars[1]).toEqual(MENU_PAGE_IDS.map((id) => PAGES[id].path))
  })

  it.each(MENU_PAGE_IDS)('%s links to its path, and at that path shows its own heading with the item marked current', (id) => {
    const { path, menuLabel } = PAGES[id]
    const html = render({ path })
    expect(html).toContain(`href="${path}"`)
    const heading = headings(html)
    expect(heading).toHaveLength(1)
    expect(heading[0]).toBe(id === 'home' ? 'Good morning, Alice' : menuLabel)
    expect(new Set(currentLinks(html))).toEqual(new Set([path]))
  })

  it('marks nothing current for a path the menu does not name', () => {
    expect(currentLinks(render({ path: '/nowhere' }))).toEqual([])
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
    expect(currentLinks(html)).toEqual([])
  })
})

describe('the pages', () => {
  it('give every heading a tabindex so focus can move to it', () => {
    for (const path of [...MENU_PAGE_IDS.map((id) => PAGES[id].path), '/settings', '/nowhere']) {
      const tags = [...render({ path }).matchAll(/<h1\b[^>]*>/g)]
      expect(tags.length, path).toBeGreaterThan(0)
      expect(tags.every((tag) => tag[0].includes('tabindex="-1"')), path).toBe(true)
    }
  })

  it('say they are not built yet, under a lead line', () => {
    const html = render({ path: '/workflows' })
    expect(text(mainOf(html))).toContain('Your team’s repeated tasks.')
    expect(text(mainOf(html))).toContain('This page is not built yet.')
  })

  it('open Home with the greeting and today in Singapore time', () => {
    const main = text(mainOf(render()))
    expect(main).toContain('Good morning, Alice')
    expect(main).toContain('Thursday 29 October.')
  })

  it('never use the retired names', () => {
    for (const path of ['/', '/workflows', '/software', '/agents', '/settings', '/nowhere']) {
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
    expect(menuLabels(html)).toEqual(['Home', 'Workflows', 'Software watchlist', 'Agent library'])
    expect(headerOf(html)).not.toContain('Operator')
  })

  it('does not say so for a refusal below 500', () => {
    expect(headings(render({ meError: new ApiError(403, null) }))).toEqual(['Good morning'])
  })

  it('keeps the test controls, so a stale person can be swapped', () => {
    expect(render({ meError: new ApiError(401, null) })).toContain('Test controls')
  })
})
