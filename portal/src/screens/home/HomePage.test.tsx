import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import dayOne from '../../../../contracts/fixtures/builder/home.day-one.json'
import { App } from '../../App'
import { needsTotal } from './home'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import type { ApprovalItem, CapabilitiesView, HomeOut, Me } from '../../api/types'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const ERIN: Me = { id: 'erin', display: 'Erin', roles: ['operator'] }

const BOB_HOME = bobHome as HomeOut
const ALICE_HOME = aliceHome as HomeOut
const DAY_ONE = dayOne as HomeOut
const NOW = new Date('2026-11-03T15:00:00+08:00')

const CAPABILITIES = capabilities as CapabilitiesView
const NO_MODEL = { active: null, available: true, changes: [], pending: null, providers: [], unavailable_message: null, you_can_change: true }
const MODEL = { ...NO_MODEL, active: { provider: 'mock', model: 'mock-model' } }

interface Seed {
  readonly model?: 'none' | 'connected'
}

function render(me: Me, home: HomeOut | Error | 'loading' | { readonly stale: HomeOut }, seed: Seed = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['capabilities', scope], CAPABILITIES)
  if (seed.model) queryClient.setQueryData(['model-settings', scope], seed.model === 'none' ? NO_MODEL : MODEL)
  const homeQuery = () => queryClient.getQueryCache().build(queryClient, { queryKey: ['home', scope] })
  if (home instanceof Error) homeQuery().setState({ status: 'error', error: home, fetchStatus: 'idle' })
  else if (home !== 'loading' && 'stale' in home) homeQuery().setState({ status: 'error', data: home.stale, error: new ApiError(503, null), fetchStatus: 'idle' })
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
const headingsOf = (html: string) => [...html.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/g)].map((m) => text(m[1] ?? ''))
const primaries = (html: string) => (html.match(/class="[^"]*_primary_[^"]*"/g) ?? []).length

describe('Home for an Approver with a run waiting for his yes', () => {
  const html = mainOf(render(BOB, BOB_HOME))

  it('says how many things need him under the greeting, and what runs next', () => {
    expect(text(html)).toContain('Good afternoon! Bob 3 things need you.')
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
    expect(linksIn(itemOf(html, 'confirmation:cfm_01JADDR'))).toEqual([['Review in Settings', '/settings?tab=model']])
  })

  it('never offers a decision on Home', () => {
    expect([...buttonsIn(html), ...linksIn(html).map(([name]) => name)].filter((name) => /^(Approve|Decline|Confirm|Not now)/.test(name ?? ''))).toEqual([])
  })

  it('has no box, no suggestions and nothing to create, only the note that says why', () => {
    expect(html).not.toContain('<textarea')
    expect(html).not.toContain('Planner')
    expect(html).not.toContain('Waiting on others')
    expect(html).not.toContain('Your drafts')
    expect(buttonsIn(html)).not.toContain('How it works')
    expect(text(html)).toContain('You’re an Approver, so you decide on requests. Operators set up workflows.')
  })
})

describe('Home for the Operator who started that run', () => {
  const html = mainOf(render(ALICE, ALICE_HOME))

  it('sends a connection that does not work to the Connections tab in Settings, with nothing to press here', () => {
    const item = itemOf(html, 'connection:jira')
    expect(buttonsIn(item)).toEqual([])
    expect(linksIn(item)).toEqual([['See it in Settings', '/settings?tab=connections']])
  })

  it('shows her stopped run with the AI troubleshooter’s reason, a retry, and the run', () => {
    const card = itemOf(html, 'stopped:run_01JB9')
    expect(text(card)).toContain('Software watchlist stopped')
    expect(text(card)).toContain('AI troubleshooter An agent could not finish its work. Retry the run. If it fails again, check whether that service is up.')
    expect(buttonsIn(card)).toEqual(['Retry the run'])
    expect(linksIn(card)).toEqual([['See the run', '/runs/run_01JB9']])
  })

  it('no longer lists the run waiting for someone else’s yes, because Waiting on others is on Workflows', () => {
    expect(ALICE_HOME.waiting_on_others).toHaveLength(1)
    expect(html).not.toContain('Waiting on others')
    expect(html).not.toContain('data-waiting')
  })

  it('counts the team’s unread reply in Needs you', () => {
    const quiet: HomeOut = { ...ALICE_HOME, stopped: [], stopped_total: 0, approvals: [], approvals_total: 0, confirmations: [], connections: [], addresses: [] }
    const reply = mainOf(render(ALICE, quiet))
    expect(text(reply)).toContain('Needs you 1')
    expect(text(itemOf(reply, 'reply:trq_01JD5RP'))).toContain('Bob replied to your report')
    expect(linksIn(itemOf(reply, 'reply:trq_01JD5RP'))).toEqual([['Read the reply', '/workflows?request=trq_01JD5RP']])
  })

  it('no longer lists her drafts, because Your drafts is on Workflows', () => {
    expect(ALICE_HOME.drafts).toHaveLength(1)
    expect(html).not.toContain('Your drafts')
    expect(html).not.toContain('data-draft')
  })
})

describe('Home on day one', () => {
  const html = mainOf(render(ERIN, DAY_ONE))

  it('asks what the team does again and again, with the box and the platform’s three starting points', () => {
    expect(headingsOf(html)).toEqual(['What does your team do again and again?'])
    expect(text(html)).toContain('Tell me a task in plain English.')
    expect(html).toContain('<textarea')
    expect(buttonsIn(html)).toEqual(expect.arrayContaining(CAPABILITIES.examples.map((example) => example.text)))
    expect(text(html)).not.toContain('Start your first workflow')
    expect(sectionOf(html, 'Needs you')).toBe('')
  })

  it('shows the I can list from the registry, with the not yet list folded under one question', () => {
    expect(text(html)).toContain('I can Read Jira tickets')
    expect(html).toMatch(/<details[^>]*>\s*<summary[^>]*>What can’t I do yet\?<\/summary>/)
    expect(text(html)).toContain('Find tickets by their component or priority')
  })

  it('names no connection warning and no count, so a fresh account is not scared', () => {
    expect(text(html)).not.toMatch(/running out|needs attention/i)
  })

  it('keeps an Approver on all quiet, with no first workflow', () => {
    const approver = mainOf(render(BOB, DAY_ONE))
    expect(text(sectionOf(approver, 'Needs you'))).toContain('All quiet Nothing is scheduled yet.')
    expect(approver).not.toContain('<textarea')
  })
})

describe('Home for an Operator in a normal week', () => {
  const html = mainOf(render(ALICE, ALICE_HOME))

  it('puts the box and three suggestions above Needs you, with the heading and the one-line state', () => {
    expect(headingsOf(html)).toEqual(['Good afternoon! Alice'])
    expect(text(html)).toContain('Some things need you.')
    expect(html).toContain('<textarea')
    expect(html.indexOf('<textarea')).toBeLessThan(html.indexOf('Needs you'))
    const chips = [...html.matchAll(/<button[^>]*class="[^"]*_chip_[^"]*"[^>]*>([^<]*)<\/button>/g)].map((m) => m[1])
    expect(chips).toEqual(['Check my workflows', 'What can I ask for?', 'Set up another workflow'])
  })

  it('offers “Why did X stop” instead when a stop is not already the first Needs you row', () => {
    const quiet = mainOf(render(ALICE, { ...ALICE_HOME, approvals: [], approvals_total: 0, confirmations: [], connections: [], addresses: [], replied: [], stopped_total: 1 }))
    expect(quiet).toContain('Check my workflows')
    expect(quiet).not.toContain('Why did Software watchlist stop?')
  })

  it('has one primary button, the first Needs you row’s action', () => {
    expect(primaries(html)).toBe(1)
  })

  it('names the send button for a screen reader, and labels the box', () => {
    expect(html).toContain('aria-label="Send to the Planner"')
    expect(html).toMatch(/<label[^>]*for="planner-box"[^>]*>Describe a task for the Planner<\/label>/)
    expect(html).toContain('placeholder="What would you like to automate, check or fix?"')
  })
})

describe('Home with no working AI model', () => {
  const html = mainOf(render(ALICE, ALICE_HOME, { model: 'none' }))

  it('says it can’t read new requests and offers Connect a model, and no box', () => {
    expect(headingsOf(html)).toEqual(['I can’t read new requests until an AI model is connected'])
    expect(linksIn(html)).toContainEqual(['Connect a model', '/settings?tab=model'])
    expect(html).not.toContain('placeholder="What would you like')
  })

  it('still shows the lists, Ask the team and Needs you, without the model’s own row', () => {
    expect(text(html)).toContain('I can Read Jira tickets')
    expect(buttonsIn(html)).toContain('Ask the team for something new')
    expect(html).toContain('data-home-item="stopped:run_01JB9"')
    expect(html).not.toContain('data-home-item="connection:model"')
  })

  it('keeps the count the platform gives, so the tab and the heading agree', () => {
    const withModelRow: HomeOut = { ...ALICE_HOME, connections: [{ ...ALICE_HOME.connections[0]!, id: 'model', name: 'AI model' }] }
    const offline = text(mainOf(render(ALICE, withModelRow, { model: 'none' })))
    expect(offline).toContain(`Needs you ${needsTotal(withModelRow)}`)
    expect(mainOf(render(ALICE, withModelRow, { model: 'none' }))).not.toContain('data-home-item="connection:model"')
  })
})

describe('Home with nothing to do on a team with workflows', () => {
  it('says nothing needs you right now and names what runs next', () => {
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals: [], approvals_total: 0, confirmations: [] }))
    expect(text(html)).toContain('Nothing needs you right now.')
    expect(text(html)).toContain('All quiet Next up: Software watchlist , Mon 9 Nov, 9:00.')
    expect(html).not.toContain('Coming up next')
  })

  it('names London next to what runs next when its schedule is in London, in both places, as the workflow page does', () => {
    const london = { ...BOB_HOME.coming_up!, name: 'Watch LangGraph', template: 'agent_cards', next_run_at: '2026-11-03T09:00:00Z', time_zone: 'Europe/London' }
    const busy = mainOf(render(BOB, { ...BOB_HOME, coming_up: london }))
    const quiet = mainOf(render(BOB, { ...BOB_HOME, approvals: [], approvals_total: 0, confirmations: [], coming_up: london }))
    expect(text(busy)).toContain('Coming up next: Watch LangGraph , Today, 9:00 London time.')
    expect(text(quiet)).toContain('All quiet Next up: Watch LangGraph , Today, 9:00 London time.')
  })
})

describe('Home with many runs waiting', () => {
  it('shows the newest ten and says how many more are waiting', () => {
    const [ask] = BOB_HOME.approvals as [ApprovalItem]
    const approvals = Array.from({ length: 10 }, (_, n) => ({ ...ask, run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:${String(n).padStart(2, '0')}:00Z` }))
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals, approvals_total: 50, confirmations: [] }))
    expect([...html.matchAll(/data-home-item=/g)]).toHaveLength(10)
    expect(/data-home-item="([^"]+)"/.exec(html)?.[1]).toBe('approval:apr_9')
    expect(text(html)).toContain('50 requests are waiting for your yes.')
    expect(text(html)).toContain('40 more runs are waiting for your yes.')
  })
})

describe('Home before it knows', () => {
  it('keeps the greeting and says it is loading', () => {
    const html = mainOf(render(BOB, 'loading'))
    expect(text(html)).toContain('Loading what needs you')
    expect(headingsOf(html)).toEqual([])
  })

  it('says it could not load, and offers to try again', () => {
    const html = mainOf(render(BOB, new ApiError(500, null)))
    expect(html).toMatch(/<p[^>]*role="alert"[^>]*>Home could not be loaded\.<\/p>/)
    expect(buttonsIn(html)).toEqual(['Try again'])
  })
})

describe('Home when a refresh fails', () => {
  it('keeps what it showed and says quietly that it could not refresh', () => {
    const html = mainOf(render(BOB, { stale: BOB_HOME }))
    expect(text(itemOf(html, 'approval:apr_01JB8'))).toContain('1 ticket is waiting for your yes')
    expect(html).toMatch(/<p[^>]*role="status"[^>]*>Could not refresh\. Trying again in a moment\.<\/p>/)
    expect(html).not.toContain('role="alert"')
  })

  it('says nothing about refreshing while the refreshes work', () => {
    expect(text(mainOf(render(BOB, BOB_HOME)))).not.toContain('Could not refresh')
  })
})

describe('Home for an Operator with more than three things waiting', () => {
  const approvals = Array.from({ length: 5 }, (_, n): ApprovalItem => ({ ...(BOB_HOME.approvals[0] as ApprovalItem), run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:0${n}:00Z` }))
  const busy: HomeOut = { ...ALICE_HOME, approvals, approvals_total: 5 }
  const total = 5 + ALICE_HOME.confirmations.length + ALICE_HOME.stopped_total + ALICE_HOME.replied.length + ALICE_HOME.connections.length + ALICE_HOME.addresses.length

  it('shows the three most urgent, stopped runs first, and links to the rest on Workflows', () => {
    const html = mainOf(render(ALICE, busy))
    const keys = [...html.matchAll(/data-home-item="([^"]+)"/g)].map((match) => match[1])
    expect(keys).toEqual(['stopped:run_01JB9', 'approval:apr_4', 'approval:apr_3'])
    expect(text(html)).toContain(`Needs you ${total}`)
    expect(linksIn(html)).toContainEqual(['See all on Workflows', '/workflows'])
  })

  it('shows an Approver who is not an Operator the whole list instead, with no link', () => {
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals, approvals_total: 5 }))
    expect([...html.matchAll(/data-home-item="/g)]).toHaveLength(5 + BOB_HOME.confirmations.length)
    expect(text(html)).not.toContain('on Workflows')
  })
})
