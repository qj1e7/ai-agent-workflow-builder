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
  /** How many software the watchlist holds. Left out, the watchlist is empty. */
  readonly watching?: number
}

function render(me: Me, home: HomeOut | Error | 'loading' | { readonly stale: HomeOut }, seed: Seed = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['capabilities', scope], CAPABILITIES)
  queryClient.setQueryData(['watchlist', scope], { software: Array.from({ length: seed.watching ?? 0 }, () => ({})) })
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
const chipsOf = (html: string, name = 'Suggestions') => buttonsIn(new RegExp(`<div[^>]*role="group"[^>]*aria-label="${name}"[^>]*>([\\s\\S]*?)</div>`).exec(html)?.[1] ?? '')
const keysOf = (html: string) => [...html.matchAll(/data-home-item="([^"]+)"/g)].map((m) => m[1])
const groupsOf = (html: string) =>
  [...html.matchAll(/<h2 id="[^"]*">(Do now|Set up)<\/h2><ul[^>]*>([\s\S]*?)<\/ul><\/li>/g)].map((m) => [m[1], [...(m[2] ?? '').matchAll(/data-home-item="([^"]+)"/g)].map((k) => k[1])] as const)

describe('Home for an Operator in a normal week (A1 to A7)', () => {
  const html = mainOf(render(ALICE, ALICE_HOME, { watching: 2 }))

  it('greets her in a small line, then asks the one question as the heading', () => {
    expect(html).toMatch(/<p[^>]*>Good afternoon, Alice<\/p>/)
    expect(headingsOf(html)).toEqual(['What should run by itself?'])
    expect(html.indexOf('Good afternoon, Alice')).toBeLessThan(html.indexOf('What should run by itself?'))
  })

  it('has the Planner’s face at 96 px above the greeting', () => {
    const face = /<svg[^>]*width="(\d+)"/.exec(html)
    expect(face?.[1]).toBe('96')
    expect(html.indexOf(face?.[0] ?? '-')).toBeLessThan(html.indexOf('Good afternoon, Alice'))
  })

  it('has one box with the sketch’s words for everyone, and a send button named Send', () => {
    expect(html).toContain('placeholder="Ask, or describe a task"')
    expect(html).toMatch(/<label[^>]*for="planner-box"[^>]*>Ask, or describe a task<\/label>/)
    expect(html).toContain('aria-label="Send"')
  })

  it('offers the sketch’s three chips under the box, and no What can I ask for?', () => {
    expect(chipsOf(html)).toEqual(['What needs me?', 'Which software is behind?', 'What can you do?'])
    expect(html.indexOf('<textarea')).toBeLessThan(html.indexOf('What needs me?'))
    expect(html).not.toContain('What can I ask for?')
    expect(html).not.toMatch(/I can Check software/)
  })

  it('lists what needs her as plain rows under Do now and Set up, the most urgent five, each one link with the subject in bold, and no buttons', () => {
    const [doNow, setUp] = groupsOf(html)
    expect(doNow).toEqual(['Do now', ['stopped:run_01JB9', 'connection:jira', 'reply:trq_01JD5RP']])
    expect(setUp?.[0]).toBe('Set up')
    expect(setUp?.[1]).toHaveLength(2)
    const rows = /<ul[^>]*aria-label="Needs you"[^>]*>([\s\S]*?)<\/ul><\/li><\/ul>/.exec(html)?.[1] ?? ''
    expect(linksIn(rows).slice(0, 4)).toEqual([
      ['Software watchlist stopped Wed 4 Nov at 10:14', '/runs/run_01JB9'],
      ['Jira isn’t answering', '/settings?tab=connections'],
      ['Bob replied to your report', '/workflows?request=trq_01JD5RP'],
      ['GitHub key expires Wed 18 Nov', '/settings?tab=connections'],
    ])
    expect(rows).toContain('<b>Software watchlist</b> stopped Wed 4 Nov at 10:14')
    expect(buttonsIn(rows)).toEqual([])
    expect(linksIn(html), 'the sixth is one more, on Workflows').toContainEqual(['1 more that need you', '/workflows'])
  })

  it('has no Needs you heading, no count and no AI troubleshooter box on Home', () => {
    expect(sectionOf(html, 'Needs you')).toBe('')
    expect(text(html)).not.toContain('Needs you')
    expect(text(html)).not.toContain('AI troubleshooter')
  })

  it('has no main button of its own: the box is where she starts', () => {
    expect(primaries(html)).toBe(0)
  })

  it('shows the day-one pair while nothing is watched', () => {
    const empty = mainOf(render(ALICE, ALICE_HOME))
    expect(empty).toContain('aria-label="Starting points"')
    expect(chipsOf(empty, 'Starting points')).toEqual(['Keep track of the LangGraph version', 'What can you do?'])
  })

  it('sets up no general workflow from a chip', () => {
    expect(html).not.toMatch(/Set up another workflow|Every Friday|Check my workflows/)
  })
})

describe('Home for an Approver with a run waiting for his yes', () => {
  const html = mainOf(render(BOB, BOB_HOME))

  it('greets him, then says how many things need him as the heading', () => {
    expect(html).toMatch(/<p[^>]*>Good afternoon, Bob<\/p>/)
    expect(headingsOf(html)).toEqual(['3 things need you'])
    const one = mainOf(render(BOB, { ...BOB_HOME, confirmations: [] }))
    expect(headingsOf(one), 'the sketch’s words when only his yes is wanted').toEqual(['1 change waits for your yes'])
  })

  it('has the same box, the sketch’s three chips, then every row that needs him (ROLE-home)', () => {
    expect(html).toContain('placeholder="Ask, or describe a task"')
    expect(chipsOf(html)).toEqual(['What waits for me?', 'What did I decide?', 'What can you do?'])
    const at = ['<textarea', 'What waits for me?', 'Do now'].map((mark) => html.indexOf(mark))
    expect(at.every((place, index) => place >= 0 && (index === 0 || place > (at[index - 1] ?? 0)))).toBe(true)
    expect(keysOf(html)).toHaveLength(needsTotal(BOB_HOME))
  })

  it('puts the waiting run first, under Do now, as a row that opens the run at the decision', () => {
    expect(groupsOf(html)).toEqual([
      ['Do now', ['approval:apr_01JB8']],
      ['Set up', ['confirmation:cfm_01JADDR', 'confirmation:cfm_01JD4VE']],
    ])
    expect(linksIn(html)).toContainEqual(['Software watchlist needs your yes', '/runs/run_01JB8'])
    expect(linksIn(html)).toContainEqual(['Dave waits to be confirmed as an Approver', '/settings?tab=people'])
  })

  it('never offers a decision on Home', () => {
    expect([...buttonsIn(html), ...linksIn(html).map(([name]) => name)].filter((name) => /^(Approve|Decline|Confirm|Not now|Review and decide)/.test(name ?? ''))).toEqual([])
  })

  it('offers nothing to set up, and no note, as in the sketch', () => {
    expect(html).not.toContain('What can I ask for?')
    expect(html).not.toContain('Waiting on others')
    expect(html).not.toContain('Your drafts')
    expect(text(html)).not.toContain('You’re an Approver')
  })
})

describe('Home for the Operator who started that run', () => {
  const html = mainOf(render(ALICE, ALICE_HOME))

  it('no longer lists the run waiting for someone else’s yes, because Waiting on others is on Workflows', () => {
    expect(ALICE_HOME.waiting_on_others).toHaveLength(1)
    expect(html).not.toContain('Waiting on others')
    expect(html).not.toContain('data-waiting')
  })

  it('counts the team’s unread reply in her rows', () => {
    const quiet: HomeOut = { ...ALICE_HOME, stopped: [], stopped_total: 0, approvals: [], approvals_total: 0, confirmations: [], connections: [], addresses: [] }
    const reply = mainOf(render(ALICE, quiet))
    expect(keysOf(reply)).toEqual(['reply:trq_01JD5RP'])
  })

  it('no longer lists her drafts, because Your drafts is on Workflows', () => {
    expect(ALICE_HOME.drafts).toHaveLength(1)
    expect(html).not.toContain('Your drafts')
    expect(html).not.toContain('data-draft')
  })
})

describe('Home on day one', () => {
  const html = mainOf(render(ERIN, DAY_ONE))

  it('asks the sketch’s question, with the box and the platform’s two starting points as chips', () => {
    expect(headingsOf(html)).toEqual(['What should run by itself?'])
    expect(html).toContain('<textarea')
    expect(chipsOf(html, 'Starting points')).toEqual(CAPABILITIES.examples.map((example) => example.text))
    expect(text(html)).not.toContain('Start your first workflow')
    expect(keysOf(html)).toEqual([])
  })

  it('leaves what the Planner can do to the What can you do? chip, with no list on Home', () => {
    expect(text(html)).not.toContain('I can Check software')
    expect(html).not.toContain('<details')
  })

  it('names no connection warning and no count, so a fresh account is not scared', () => {
    expect(text(html)).not.toMatch(/running out|needs attention|isn’t answering/i)
  })

  it('gives an Approver his box for questions and no first workflow', () => {
    const approver = mainOf(render(BOB, DAY_ONE))
    expect(headingsOf(approver)).toEqual(['Nothing waits for your yes'])
    expect(approver).toContain('<textarea')
    expect(text(approver)).not.toContain('What should run by itself?')
    expect(keysOf(approver)).toEqual([])
  })
})

describe('Home with no working AI model', () => {
  const html = mainOf(render(ALICE, ALICE_HOME, { model: 'none' }))

  it('says it can’t read new requests and offers Connect a model, and no box', () => {
    expect(headingsOf(html)).toEqual(['I can’t read new requests until an AI model is connected'])
    expect(linksIn(html)).toContainEqual(['Connect a model', '/settings?tab=model'])
    expect(html).not.toContain('<textarea')
  })

  it('still shows the lists and Needs you, and no Ask the team', () => {
    expect(text(html)).toContain('I can Check software for new releases on GitHub Create a Jira ticket after a yes')
    expect(buttonsIn(html)).not.toContain('Ask the team for something new')
    expect(html).toContain('data-home-item="stopped:run_01JB9"')
  })

  const MODEL_ROW = { id: 'model', name: 'AI model', state: 'not_set_up', problem: 'No AI model is turned on.', fix: 'Add an AI model under Settings, AI model.', checked_at: null, last_ok_at: null, expires_at: null } as const
  const withModelRow: HomeOut = { ...ALICE_HOME, connections: [...ALICE_HOME.connections, MODEL_ROW] }

  it('lists the model’s own row, pointing to the button above it, so every row the count includes is listed (FIX-offline-count)', () => {
    const page = mainOf(render(ALICE, withModelRow, { model: 'none' }))
    expect(text(page)).toContain(`Needs you ${needsTotal(withModelRow)}`)
    const row = itemOf(page, 'connection:model')
    expect(text(row)).toContain('No AI model connected Connect one with the button above.')
    expect(linksIn(row).map(([name]) => name)).not.toContain('Connect a model')
    expect(linksIn(page).filter(([name]) => name === 'Connect a model')).toHaveLength(1)
  })
})

describe('An Approver’s Home with no AI model (ROLE-offline)', () => {
  const html = mainOf(render(BOB, BOB_HOME, { model: 'none' }))

  it('says the Planner can’t answer and who can connect one, with no box and no Connect a model', () => {
    expect(headingsOf(html)).toEqual(['I can’t answer questions until an AI model is connected'])
    expect(text(html)).toContain('An Operator can connect one in Settings. 3 things need you.')
    expect(html).not.toContain('<textarea')
    expect(linksIn(html).map(([name]) => name)).not.toContain('Connect a model')
  })

  it('keeps his request first, with Review and decide as the one main button', () => {
    expect(/data-home-item="([^"]+)"/.exec(html)?.[1]).toBe('approval:apr_01JB8')
    expect(linksIn(itemOf(html, 'approval:apr_01JB8'))).toEqual([['Review and decide', '/runs/run_01JB8']])
    expect(primaries(html)).toBe(1)
  })
})

describe('Home with many runs waiting', () => {
  it('shows the newest ten and says how many more are waiting', () => {
    const [ask] = BOB_HOME.approvals as [ApprovalItem]
    const approvals = Array.from({ length: 10 }, (_, n) => ({ ...ask, run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:${String(n).padStart(2, '0')}:00Z` }))
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals, approvals_total: 50, confirmations: [] }))
    expect(keysOf(html)).toHaveLength(10)
    expect(keysOf(html)[0]).toBe('approval:apr_9')
    expect(headingsOf(html)).toEqual(['50 changes wait for your yes'])
    expect(text(html)).toContain('40 more runs are waiting for your yes.')
  })
})

describe('Home before it knows', () => {
  it('says it is loading, with no heading yet', () => {
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
    expect(text(itemOf(html, 'approval:apr_01JB8'))).toContain('Software watchlist needs your yes')
    expect(html).toMatch(/<p[^>]*role="status"[^>]*>Could not refresh\. Trying again in a moment\.<\/p>/)
    expect(html).not.toContain('role="alert"')
  })

  it('says nothing about refreshing while the refreshes work', () => {
    expect(text(mainOf(render(BOB, BOB_HOME)))).not.toContain('Could not refresh')
  })
})

describe('Home for an Operator with more than five things waiting', () => {
  const approvals = Array.from({ length: 5 }, (_, n): ApprovalItem => ({ ...(BOB_HOME.approvals[0] as ApprovalItem), run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:0${n}:00Z` }))
  const busy: HomeOut = { ...ALICE_HOME, approvals, approvals_total: 5 }

  it('shows the five most urgent, stopped runs first, and “N more” to the rest on Workflows', () => {
    const html = mainOf(render(ALICE, busy))
    expect(keysOf(html)).toEqual(['stopped:run_01JB9', 'approval:apr_4', 'approval:apr_3', 'approval:apr_2', 'approval:apr_1'])
    expect(text(html)).toContain('Do now')
    expect(linksIn(html)).toContainEqual([`${String(needsTotal(busy) - 5)} more that need you`, '/workflows'])
  })

  it('shows an Approver who is not an Operator the whole list instead, with no link', () => {
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals, approvals_total: 5 }))
    expect(keysOf(html)).toHaveLength(5 + BOB_HOME.confirmations.length)
    expect(text(html)).not.toContain('on Workflows')
  })
})

describe('Needs you in two groups on Home', () => {
  const [jira] = ALICE_HOME.connections
  const busy: HomeOut = { ...ALICE_HOME, connections: [jira!, { ...ALICE_HOME.connections[1]! }], approvals_total: 0 }

  it('shows Home’s five from Do now first, so a Set up item never takes the place of one to do now', () => {
    const html = mainOf(render(BOB, { ...BOB_HOME, approvals: [], approvals_total: 0 }))
    expect(groupsOf(html)).toEqual([['Set up', ['confirmation:cfm_01JADDR', 'confirmation:cfm_01JD4VE']]])
    const approvals = Array.from({ length: 3 }, (_, n): ApprovalItem => ({ ...(BOB_HOME.approvals[0] as ApprovalItem), run_id: `run_${n}`, approval_id: `apr_${n}`, started_at: `2026-11-03T01:0${n}:00Z` }))
    const all = mainOf(render(ALICE, { ...busy, approvals, approvals_total: 3 }))
    expect(groupsOf(all)).toEqual([['Do now', ['stopped:run_01JB9', 'approval:apr_2', 'approval:apr_1', 'approval:apr_0', 'connection:jira']]])
    expect(text(all)).toMatch(/\d+ more that need you/)
  })

  it('tints a row by what it needs: red for a stop or a broken connection, amber for the rest', () => {
    const html = mainOf(render(BOB, BOB_HOME))
    expect(itemOf(html, 'approval:apr_01JB8')).toMatch(/data-tone="wait"/)
    const alice = mainOf(render(ALICE, ALICE_HOME, { watching: 2 }))
    expect(itemOf(alice, 'stopped:run_01JB9')).toMatch(/data-tone="err"/)
    expect(itemOf(alice, 'connection:jira')).toMatch(/data-tone="err"/)
  })
})
