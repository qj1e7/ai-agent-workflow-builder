import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import cardsFixture from '../../../../contracts/fixtures/cards/list.json'
import toolsFixture from '../../../../contracts/fixtures/cards/tools.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { CardView, Me, ToolView } from '../../api/types'
import { CARDS_UNAVAILABLE_WORDS, NOT_FOUND_WORDS } from './AgentsPage'
import { CHANGE_LATER_NOTE, PLATFORM_NOTE, TOOLS_UNAVAILABLE_WORDS } from './agents'

const CARDS = cardsFixture.cards as unknown as CardView[]
const TOOLS = toolsFixture.tools as unknown as ToolView[]
const ALICE: Me = { id: '0a11ce00-0000-4000-8000-000000000001', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: '0b0b0000-0000-4000-8000-000000000002', display: 'Bob', roles: ['approver'] }

interface Setup {
  readonly path?: string
  readonly me?: Me
  readonly cards?: CardView[] | Error
  readonly tools?: ToolView[] | Error
}

function render({ path = '/agents', me = ALICE, cards = CARDS, tools = TOOLS }: Setup = {}): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  const seed = (key: readonly unknown[], value: unknown) => {
    if (value instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: value, fetchStatus: 'idle' })
    else queryClient.setQueryData(key, value)
  }
  queryClient.setQueryData(['me', session.cacheScope()], me)
  seed(['agent-cards', session.cacheScope()], cards)
  seed(['tools'], tools)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>
          <App now={() => new Date('2026-10-29T03:00:00Z')} />
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

describe('the Agent library list', () => {
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
    expect(html).toContain('href="/agents/crd_version_checker"')
    expect(html).toContain('href="/agents/planner"')
  })

  it('looks the same to an Approver, with no change controls', () => {
    const forBob = mainOf(render({ me: BOB }))
    expect(forBob).toBe(mainOf(render()))
    expect(forBob).not.toMatch(/Suggest a change|Save as version|What should change/)
  })
})

describe('a card', () => {
  it('opens on its address with its steps and tools, and says a write waits for a yes', () => {
    const dialog = text(dialogOf(render({ path: '/agents/crd_version_checker' })))
    expect(dialog).toContain('Version checker')
    expect(dialog).toContain('Version 1. Ships with the platform')
    expect(dialog).toContain('Read the newest releases of the repository.')
    for (const name of ['Read GitHub releases', 'Search Jira', 'Create a Jira ticket']) expect(dialog).toContain(name)
    expect(dialog).toContain('Changes data Create a Jira ticket Waits for a yes from 1 Approver')
    expect(dialog).toContain(CHANGE_LATER_NOTE)
    expect(dialog).toContain('Close')
  })

  it('has a Close button at the top, beside its title, and another after the card', () => {
    for (const path of ['/agents/crd_version_checker', '/agents/planner']) {
      const dialog = dialogOf(render({ path }))
      const top = dialog.indexOf('aria-label="Close"')
      expect(top).toBeGreaterThan(dialog.indexOf('<h2'))
      expect(top).toBeLessThan(dialog.indexOf('How it works'))
      expect(dialog.lastIndexOf('>Close</button>')).toBeGreaterThan(dialog.indexOf('How it works'))
    }
  })

  it('labels the dialog with its title', () => {
    const dialog = dialogOf(render({ path: '/agents/crd_version_checker' }))
    const labelled = /aria-labelledby="([^"]+)"/.exec(dialog)?.[1]
    expect(dialog).toContain(`<h2 id="${labelled}">Version checker</h2>`)
  })

  it('says only the team that runs the platform can change the Planner', () => {
    const dialog = text(dialogOf(render({ path: '/agents/planner' })))
    expect(dialog).toContain(PLATFORM_NOTE)
    expect(dialog).toContain('Platform agent')
    expect(dialog).not.toContain(CHANGE_LATER_NOTE)
  })

  it('says so when the address names no agent', () => {
    const html = render({ path: '/agents/crd_nothing' })
    expect(dialogOf(html)).toBe('')
    expect(mainOf(html)).toContain(NOT_FOUND_WORDS)
  })

  it('lists tool ids when the tool list is down', () => {
    const dialog = text(dialogOf(render({ path: '/agents/crd_version_checker', tools: down })))
    expect(dialog).toContain('jira.create_ticket')
    expect(dialog).toContain('Waits for a yes from 1 Approver')
  })
})

describe('the Tools tab', () => {
  it('lists the four tools, marks jira.create_ticket as a write that waits for a yes, and names who uses each', () => {
    const html = render({ path: '/agents?tab=tools' })
    const main = mainOf(html)
    expect((html.match(/<li class="[^"]*" data-tool-id=/g) ?? []).length).toBe(4)
    expect(main).toContain('Tools that change data 1')
    expect(main).toContain('Tools that only read 3')
    expect(main).toContain('Create a Jira ticket jira.create_ticket')
    expect(main).toContain('Changes data Waits for a yes from 1 Approver')
    expect(main).toContain('Used by Version checker')
    expect(main).toContain('No agent uses it yet')
    expect(main).not.toContain('Platform agents')
  })
})

describe('when the agent runtime is down', () => {
  it('says the tool list is not available and keeps the cards', () => {
    const html = render({ tools: down })
    const main = mainOf(html)
    expect(main).toContain(TOOLS_UNAVAILABLE_WORDS)
    expect(tileNames(html)).toEqual(['Planner', 'AI troubleshooter', 'Version checker', 'Weekly summary'])
  })

  it('says it on the Tools tab too, with no tool rows', () => {
    const html = render({ path: '/agents?tab=tools', tools: down })
    expect(mainOf(html)).toContain(TOOLS_UNAVAILABLE_WORDS)
    expect(html).not.toContain('data-tool-id')
  })

  it('keeps the platform agents when the cards fail', () => {
    const html = render({ cards: down })
    expect(mainOf(html)).toContain(CARDS_UNAVAILABLE_WORDS)
    expect(tileNames(html)).toEqual(['Planner', 'AI troubleshooter'])
  })
})
