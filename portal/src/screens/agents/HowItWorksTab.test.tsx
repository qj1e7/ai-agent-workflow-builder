/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import cardsFixture from '../../../../contracts/fixtures/cards/list.json'
import toolsFixture from '../../../../contracts/fixtures/cards/tools.json'
import capabilitiesFixture from '../../../../contracts/fixtures/planner/capabilities.json'
import troubleFixture from '../../../../contracts/fixtures/planner/capabilities.trouble.json'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { CapabilitiesView, CardView, Me, ToolView } from '../../api/types'
import { SettingsPage } from '../settings/SettingsPage'
import { SettingsTabs } from '../settings/SettingsTabs'
import { CARDS_UNAVAILABLE_WORDS, NOT_FOUND_WORDS } from './HowItWorksTab'
import { CHANGE_LATER_NOTE, PLATFORM_NOTE, toolsUnavailableWords } from './agents'
import { CAPABILITIES_UNAVAILABLE_WORDS } from './capabilities'

const CARDS = cardsFixture.cards as unknown as CardView[]
const TOOLS = toolsFixture.tools as unknown as ToolView[]
const CAPABILITIES = capabilitiesFixture as unknown as CapabilitiesView
const TROUBLE = troubleFixture as unknown as CapabilitiesView
const ALICE: Me = { id: '0a11ce00-0000-4000-8000-000000000001', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: '0b0b0000-0000-4000-8000-000000000002', display: 'Bob', roles: ['approver'] }

const HOW = '/settings?tab=how'
const HOW_AGENTS = '/settings?tab=how&show=agents'
const agentAt = (id: string) => `/settings?tab=how&show=agents&agent=${id}`

interface Setup {
  readonly path?: string
  readonly me?: Me
  readonly cards?: CardView[] | Error
  readonly tools?: ToolView[] | Error
  readonly capabilities?: CapabilitiesView | Error
}

function render({ path = HOW_AGENTS, me = ALICE, cards = CARDS, tools = TOOLS, capabilities = CAPABILITIES }: Setup = {}): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  const seed = (key: readonly unknown[], value: unknown) => {
    if (value instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: value, fetchStatus: 'idle' })
    else queryClient.setQueryData(key, value)
  }
  queryClient.setQueryData(['me', session.cacheScope()], me)
  seed(['agent-cards', session.cacheScope()], cards)
  seed(['tools'], tools)
  seed(['capabilities', session.cacheScope()], capabilities)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>
          <main>
            <SettingsTabs now={new Date('2026-11-09T03:00:00Z')} />
          </main>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => text(/<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? '')
const dialogOf = (html: string) => /<dialog\b[\s\S]*<\/dialog>/.exec(/<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? '')?.[0] ?? ''
const tileNames = (html: string) => [...html.matchAll(/<h3><a id="agent-tile-[^"]*"[^>]*>(.*?)<\/a>/g)].map((match) => match[1])
const down = new ApiError(503, { message: 'The agent runtime is down.' })

describe('the What it can do tab', () => {
  const main = mainOf(render({ path: HOW }))

  it('opens first, with the software versioning lines grouped as I can and no Not yet group', () => {
    expect(main).toContain('What it can do')
    expect(main.indexOf('I can')).toBeGreaterThan(-1)
    expect(main).toContain('Check software for new releases on GitHub')
    expect(main).toContain('Create a Jira ticket after a yes')
    expect(main).toContain('Ask Approvers for a yes in Teams')
    const html = render({ path: HOW })
    expect(html).not.toContain('<details')
    expect(main).not.toMatch(/Read Jira tickets|Post messages in Teams|Close, edit, move|Not yet|can’t I do yet|Ask the team/)
    expect(tileNames(html)).toEqual([])
  })

  it('names the agents that use a line by their card name, and says the platform does its own', () => {
    expect(main).toContain('Used by Version checker.')
    expect(main).toContain('The platform does this for every workflow.')
  })

  it('puts no Planned or roadmap words on any line', () => {
    expect(main).not.toMatch(/\bPlanned\b|roadmap|ADR/i)
  })

  it('says what is down or needs setup, with where to fix it', () => {
    const html = render({ path: HOW, capabilities: TROUBLE })
    const words = mainOf(html)
    expect(words).toContain('Not working right now')
    expect(words).toContain('Last seen working today, 9:00')
    expect(words).toContain('Try again in a minute.')
    expect(words).not.toContain('Needs setup')
    expect(html).toContain('href="/settings?tab=connections"')
  })

  it('says it is not available when the registry is, and keeps the tabs', () => {
    const words = mainOf(render({ path: HOW, capabilities: down }))
    expect(words).toContain(CAPABILITIES_UNAVAILABLE_WORDS)
    expect(words).toContain('Agents')
  })

  it('opens an agent’s own address on the Agents tab', () => {
    expect(tileNames(render({ path: '/settings?tab=how&agent=crd_version_checker' }))).toContain('Version checker')
  })
})

describe('the Agents tab list', () => {
  it('shows the two platform agents and every card once, each with its tool count', () => {
    const html = render()
    expect(tileNames(html)).toEqual(['Planner', 'AI troubleshooter', 'Version checker', 'Weekly summary'])
    const main = mainOf(html)
    expect(main).toContain('Platform agents')
    expect(main).toContain('Specialist agents')
    expect(main.match(/Platform agent\b/g)?.length).toBe(2)
    expect(main).toContain('Changes data after a yes 3 tools')
    expect(main).toContain('Reads only 1 tool')
    expect(main).toContain('No access to other systems')
  })

  it('links each tile to its own address', () => {
    const html = render()
    expect(html).toContain('href="/settings?tab=how&amp;show=agents&amp;agent=crd_version_checker"')
    expect(html).toContain('href="/settings?tab=how&amp;show=agents&amp;agent=planner"')
  })

  it('is read only for an Operator, with no change controls', () => {
    expect(mainOf(render())).not.toMatch(/Suggest a change|Save as version|What should change/)
  })

  it('is not offered to an Approver who is not an Operator, who gets Connections instead', () => {
    const forBob = render({ me: BOB })
    expect(tileNames(forBob)).toEqual([])
    expect(mainOf(forBob)).not.toContain('Platform agents')
    expect(mainOf(forBob)).toContain('Connections')
  })
})

describe('a card', () => {
  it('opens on its address with its steps and tools, and says a write waits for a yes', () => {
    const dialog = text(dialogOf(render({ path: agentAt('crd_version_checker') })))
    expect(dialog).toContain('Version checker')
    expect(dialog).toContain('Version 1. Ships with the platform')
    expect(dialog).toContain('Read the newest releases of the repository.')
    for (const name of ['Read GitHub releases', 'Search Jira', 'Create a Jira ticket']) expect(dialog).toContain(name)
    expect(dialog).toContain('Changes data Create a Jira ticket Waits for a yes from 1 Approver')
    expect(dialog).toContain(CHANGE_LATER_NOTE)
    expect(dialog).toContain('Close')
  })

  it('numbers its How it works steps with muted markers, as the prototype’s plan does', () => {
    const dialog = dialogOf(render({ path: agentAt('crd_version_checker') }))
    expect(dialog).toMatch(/<h3>How it works<\/h3><ol\b[^>]*class="[^"]*steps[^"]*"[^>]*><li>/)
    // Vitest blanks a CSS import, so the rules are read from the file. base.css takes every list's numbers away.
    const css = readFileSync(new URL('./HowItWorks.module.css', import.meta.url), 'utf8')
    const rule = (selector: string) => new RegExp(`(^|\\n)${selector.replace(/[.:]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)?.[2] ?? ''
    expect(rule('.steps')).toMatch(/list-style:\s*decimal;/)
    expect(rule('.steps li::marker')).toMatch(/color:\s*var\(--muted\);/)
  })

  it('has a Close button at the top, beside its title, and another after the card', () => {
    for (const path of [agentAt('crd_version_checker'), agentAt('planner')]) {
      const dialog = dialogOf(render({ path }))
      const top = dialog.indexOf('aria-label="Close"')
      expect(top).toBeGreaterThan(dialog.indexOf('<h2'))
      expect(top).toBeLessThan(dialog.indexOf('How it works'))
      expect(dialog.lastIndexOf('>Close</button>')).toBeGreaterThan(dialog.indexOf('How it works'))
    }
  })

  it('tells the shell that the page moves focus itself once an agent that exists is asked for, and not otherwise', () => {
    const heading = (path: string, me: Me = ALICE) => {
      const session = createDevSession(null)
      const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
      queryClient.setQueryData(['me', session.cacheScope()], me)
      queryClient.setQueryData(['agent-cards', session.cacheScope()], CARDS)
      return (
        /<h1\b[^>]*>/.exec(
          renderToStaticMarkup(
            <QueryClientProvider client={queryClient}>
              <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
                <MemoryRouter initialEntries={[path]}>
                  <SettingsPage heading="Settings" lead="" now={new Date('2026-11-09T03:00:00Z')} />
                </MemoryRouter>
              </ApiProvider>
            </QueryClientProvider>,
          ),
        )?.[0] ?? ''
      )
    }
    expect(heading(HOW)).not.toContain('data-page-moves-focus')
    expect(heading(agentAt('crd_version_checker'))).toContain('data-page-moves-focus')
    expect(heading(agentAt('planner'))).toContain('data-page-moves-focus')
    expect(heading(agentAt('crd_nothing')), 'a missing agent opens no dialog, so the heading takes focus').not.toContain('data-page-moves-focus')
    expect(heading(agentAt('planner'), BOB), 'an Approver has no How it works').not.toContain('data-page-moves-focus')
    expect(heading('/settings?tab=people&agent=planner'), 'another tab').not.toContain('data-page-moves-focus')
  })

  it('labels the dialog with its title', () => {
    const dialog = dialogOf(render({ path: agentAt('crd_version_checker') }))
    const labelled = /aria-labelledby="([^"]+)"/.exec(dialog)?.[1]
    expect(dialog).toContain(`<h2 id="${labelled}">Version checker</h2>`)
  })

  it('says only the team that runs the platform can change the Planner', () => {
    const dialog = text(dialogOf(render({ path: agentAt('planner') })))
    expect(dialog).toContain(PLATFORM_NOTE)
    expect(dialog).toContain('Platform agent')
    expect(dialog).not.toContain(CHANGE_LATER_NOTE)
  })

  it('says what each platform agent reaches instead of other systems, in the prototype’s words', () => {
    expect(text(dialogOf(render({ path: agentAt('planner') })))).toContain('Tools it may use No access to other systems. It only plans. Rules')
    expect(text(dialogOf(render({ path: agentAt('troubleshooter') })))).toContain('Tools it may use No access to other systems. It reads the run’s own record. Rules')
  })

  it('says so when the address names no agent, as a status above the agents', () => {
    const html = render({ path: agentAt('crd_nothing') })
    expect(dialogOf(html)).toBe('')
    const notice = html.indexOf(`role="status">${NOT_FOUND_WORDS}`)
    expect(notice).toBeGreaterThan(-1)
    expect(notice).toBeLessThan(html.indexOf('Platform agents'))
  })

  it('lists tool ids when the tool list is down', () => {
    const dialog = text(dialogOf(render({ path: agentAt('crd_version_checker'), tools: down })))
    expect(dialog).toContain('jira.create_ticket')
    expect(dialog).toContain('Waits for a yes from 1 Approver')
  })
})

describe('the Tools tab', () => {
  it('lists the focus tools by name and system, marks Create a Jira ticket as a write that waits for a yes, and names who uses each', () => {
    const html = render({ path: `${HOW}&show=tools` })
    const main = mainOf(html)
    expect((html.match(/<li class="[^"]*" data-tool-id=/g) ?? []).length).toBe(2)
    expect(main).toContain('Tools that change data 1')
    expect(main).toContain('Tools that only read 1')
    expect(main).toContain('Create a Jira ticket Jira')
    expect(main).toContain('Read GitHub releases GitHub')
    expect(main).not.toContain('jira.create_ticket')
    expect(main).toContain('Changes data Waits for a yes from 1 Approver')
    expect(main).toContain('Used by Version checker')
    expect(main).not.toContain('Platform agents')
  })

  it('shows only the tools behind a focus capability, so the Jira search and read tools stay out', () => {
    const html = render({ path: `${HOW}&show=tools` })
    expect(html).not.toContain('data-tool-id="jira.search"')
    expect(html).not.toContain('data-tool-id="jira.read_ticket"')
    expect(html).toContain('data-tool-id="github.read_releases"')
    expect(html).toContain('data-tool-id="jira.create_ticket"')
  })

  it('gives each tool its health from the registry, and says what is down', () => {
    const ok = mainOf(render({ path: `${HOW}&show=tools` }))
    expect(ok).toContain('Ready. Last seen working today, 9:00.')
    expect(ok).not.toContain('Not working right now')
    const bad = mainOf(render({ path: `${HOW}&show=tools`, capabilities: TROUBLE }))
    expect(bad).toContain('Not working right now. Jira isn’t answering. Last seen working today, 9:00.')
  })

  it('offers no Draft button and no request for new tools', () => {
    const html = render({ path: `${HOW}&show=tools` })
    expect(mainOf(html)).not.toMatch(/Draft|Ask the team|new tools/)
  })

  it('leaves out a health line while the registry is not there', () => {
    expect(mainOf(render({ path: `${HOW}&show=tools`, capabilities: down }))).not.toContain('Ready.')
  })
})

describe('when the agent runtime is down', () => {
  it('says the tool list is not available and keeps the cards', () => {
    const html = render({ tools: down })
    const main = mainOf(html)
    expect(main).toContain(toolsUnavailableWords(true))
    expect(tileNames(html)).toEqual(['Planner', 'AI troubleshooter', 'Version checker', 'Weekly summary'])
    expect(mainOf(render({ path: HOW, tools: down }))).not.toContain(toolsUnavailableWords(true))
  })

  it('says it on the Tools tab too, with no tool rows and no cards below to point at', () => {
    const html = render({ path: `${HOW}&show=tools`, tools: down })
    const main = mainOf(html)
    expect(main).toContain(toolsUnavailableWords(false))
    expect(main).not.toContain('below')
    expect(html).not.toContain('data-tool-id')
  })

  it('does not point at the cards when they failed too', () => {
    const main = mainOf(render({ tools: down, cards: down }))
    expect(main).toContain(toolsUnavailableWords(false))
    expect(main).toContain(CARDS_UNAVAILABLE_WORDS)
    expect(main).not.toContain('below')
  })

  it('keeps the platform agents when the cards fail', () => {
    const html = render({ cards: down })
    expect(mainOf(html)).toContain(CARDS_UNAVAILABLE_WORDS)
    expect(tileNames(html)).toEqual(['Planner', 'AI troubleshooter'])
  })
})
