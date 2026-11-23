import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import stopped from '../../../../contracts/fixtures/builder/use-case.stopped.json'
import explainedFixture from '../../../../contracts/fixtures/builder/explain.older.json'
import advice from '../../../../contracts/fixtures/troubleshooting/failure.json'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ApprovalItem, CapabilitiesView, HomeOut, Me, NeedsPage, UseCaseView, WatchlistView, WorkflowExplained } from '../../api/types'
import { ApiError } from '../../api/client'
import { InChat } from '../../ui/fromChat'
import { escapeIsFree } from '../../ui/escape'
import { focusAfterClose, wrapTab, type PanelItem } from '../../ui/sidePanel'
import { countLine } from '../software/software'
import { needsTotal } from './home'
import { SidePanel } from './SidePanel'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const NOW = new Date('2026-11-05T15:00:00+08:00')
const STOPPED = { ...(stopped as UseCaseView), needs_you: 'stopped' } as UseCaseView
const WATCHLIST = statuses as WatchlistView
const REDIS = 'sw_01JBW00000000000000000003'
const REGISTRY = capabilities as CapabilitiesView

const EMPTY_PAGE: NeedsPage = { approvals: [], approvals_total: 0, stopped: [], stopped_total: 0, declined: [], declined_total: 0, questions_for_me: [], questions_for_me_total: 0, next: null }
const ALICE_HOME = aliceHome as HomeOut
const BOB_HOME: HomeOut = { ...(bobHome as HomeOut), setup_approvals: [] }
const OPEN_BESIDE = () => undefined

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))
const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((match) => [text(match[2] ?? ''), match[1]])

interface Options {
  me?: Me
  narrow?: boolean
  useCase?: UseCaseView
  home?: HomeOut
  useCases?: UseCaseView[]
  back?: PanelItem | null
  onOpen?: (item: PanelItem) => void
  /** The pages of Needs you that Show more has read. */
  pages?: NeedsPage[]
  explained?: { version: number | null; report: WorkflowExplained | ApiError }
}

function draw(
  item: PanelItem,
  { me = ALICE, narrow = false, useCase = STOPPED, home = me.id === 'bob' ? BOB_HOME : ALICE_HOME, useCases = [STOPPED], back = null, onOpen, pages, explained }: Options = {},
): string {
  const session = createDevSession({ getItem: () => me.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['watchlist', scope], WATCHLIST)
  queryClient.setQueryData(['capabilities', scope], REGISTRY)
  queryClient.setQueryData(['home', scope], home)
  queryClient.setQueryData(['use-cases', scope], useCases)
  queryClient.setQueryData(['use-case', scope, useCase.use_case_id], useCase)
  queryClient.setQueryData(['troubleshoot', scope, STOPPED.last_run?.run_id, 0], advice)
  if (explained) {
    const key = ['use-case', scope, STOPPED.use_case_id, 'explain', explained.version, false]
    if (explained.report instanceof ApiError) queryClient.getQueryCache().build(queryClient, { queryKey: key }).setState({ status: 'error', error: explained.report, fetchStatus: 'idle' })
    else queryClient.setQueryData(key, explained.report)
  }
  if (pages) queryClient.setQueryData(['home', scope, 'needs'], { pages, pageParams: pages.map((_, n) => (n === 0 ? null : (pages[n - 1]?.next ?? null))) })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <InChat.Provider value>
            <SidePanel item={item} back={back} now={NOW} narrow={narrow} onClose={() => undefined} onBack={() => undefined} {...(onOpen ? { onOpen } : {})} />
          </InChat.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

describe('the side panel', () => {
  it('shows one item, titled, with More details to its page and Close', () => {
    const html = draw({ kind: 'software', id: REDIS })
    expect(html.match(/id="side-panel"/g)).toHaveLength(1)
    expect(html).toMatch(/<h2[^>]*id="side-panel-h"[^>]*tabindex="-1"[^>]*>Redis<\/h2>/)
    expect(links(html)).toEqual([
      ['More details', `/software/${REDIS}`],
      ['Software watchlist', '/software'],
    ])
    expect(buttons(html)).toEqual(['Close'])
  })

  it('sits beside the chat as a region, and covers a narrow window as a dialog', () => {
    expect(draw({ kind: 'software', id: REDIS })).toMatch(/role="complementary"[^>]*aria-labelledby="side-panel-h"/)
    expect(draw({ kind: 'software', id: REDIS }, { narrow: true })).toMatch(/role="dialog" aria-modal="true" aria-labelledby="side-panel-h"/)
  })

  it('shows a software’s status, the version you run, the newest, and the workflow that checks it and when, in the Software page’s words', () => {
    const shown = text(draw({ kind: 'software', id: REDIS }))
    expect(shown).toContain('Newer out')
    expect(shown).toContain('Newest is 8.2.1. The version you run isn’t known yet.')
    expect(shown).toContain('Checked by Software watchlist')
    expect(shown).toContain('When Checked every Monday at 9:00, set by Alice. Next check')
  })

  it('shows Explain over the workflow’s name, with the report and a More details to its page', () => {
    const html = draw({ kind: 'explain', id: STOPPED.use_case_id }, { explained: { version: null, report: explainedFixture as WorkflowExplained } })
    expect(html).toMatch(/<h2[^>]*>Explain<\/h2>/)
    expect(html).toMatch(/<h3[^>]*>FastAPI release check<\/h3>/)
    expect(text(html)).toContain('Step by step 8 blocks')
    expect(links(html)).toEqual([['More details', `/workflows/${STOPPED.use_case_id}/explain`]])
    expect(buttons(html)).toEqual(['Close'])
  })

  it('titles one version Explain, version N, and its More details keeps the version', () => {
    const html = draw({ kind: 'explain', id: STOPPED.use_case_id, version: 2 }, { explained: { version: 2, report: explainedFixture as WorkflowExplained } })
    expect(html).toMatch(/<h2[^>]*>Explain, version 2<\/h2>/)
    expect(links(html)).toEqual([['More details', `/workflows/${STOPPED.use_case_id}/explain?version=2`]])
  })

  it('says it is reading while the report comes, and puts the server’s words in its place when there is nothing to explain', () => {
    expect(text(draw({ kind: 'explain', id: STOPPED.use_case_id }))).toContain('Reading the workflow')
    const words = 'Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no copy of its blocks.'
    const html = draw({ kind: 'explain', id: STOPPED.use_case_id }, { explained: { version: null, report: new ApiError(409, { detail: words }) } })
    expect(text(html)).toContain(words)
    expect(buttons(html)).toEqual(['Close'])
  })

  it('gives a failed load its reason and Try again', () => {
    const html = draw({ kind: 'explain', id: STOPPED.use_case_id }, { explained: { version: null, report: new ApiError(500, {}) } })
    expect(text(html)).toContain('The report could not be loaded.')
    expect(buttons(html)).toEqual(['Close', 'Try again'])
  })

  it('says an item that has gone is gone, with no More details', () => {
    const html = draw({ kind: 'software', id: 'sw_gone' })
    expect(text(html)).toContain('That software isn’t on the Software watchlist any more.')
    expect(links(html)).toEqual([])
  })

  it('shows a stopped workflow’s three answers with Retry, its last and next run, Open the run, and Pause, to an Operator', () => {
    const html = draw({ kind: 'workflow', id: STOPPED.use_case_id })
    const shown = text(html)
    expect(shown).toMatch(/What happened[\s\S]*Affected[\s\S]*Safe to retry[\s\S]*Last run[\s\S]*Next run/)
    expect(buttons(html)).toEqual(['Close', 'Retry', 'Pause'])
    expect(links(html)).toEqual([
      ['More details', `/workflows/${STOPPED.use_case_id}`],
      ['Open the run', `/runs/${STOPPED.last_run?.run_id ?? ''}`],
      [`Explain ${STOPPED.name}`, `/workflows/${STOPPED.use_case_id}/explain`],
    ])
  })

  it('gives an Approver who isn’t an Operator the same answers, and no control they can’t use', () => {
    const html = draw({ kind: 'workflow', id: STOPPED.use_case_id }, { me: BOB })
    expect(text(html)).toContain('Safe to retry')
    expect(text(html)).toContain('An Operator can retry the run.')
    expect(buttons(html)).toEqual(['Close'])
  })

  it('offers Resume on a paused workflow to an Operator only, as its page does', () => {
    const paused: UseCaseView = { ...STOPPED, state: 'paused' }
    expect(buttons(draw({ kind: 'workflow', id: paused.use_case_id }, { useCase: paused })), 'its last run stopped, but a paused workflow offers Resume, never Retry').toEqual(['Close', 'Resume'])
    expect(text(draw({ kind: 'workflow', id: paused.use_case_id }, { useCase: paused })), 'and no stop answers, as its page’s banner').not.toContain('Safe to retry')
    expect(buttons(draw({ kind: 'workflow', id: paused.use_case_id }, { useCase: paused, me: BOB }))).toEqual(['Close'])
    expect(text(draw({ kind: 'workflow', id: paused.use_case_id }, { useCase: paused, me: BOB }))).toContain('Next run Paused')
  })

  it('draws a run while its page’s parts load on demand, as the run page does', () => {
    const html = draw({ kind: 'run', id: 'run_01JBA' })
    expect(html).toMatch(/<h2[^>]*>Run<\/h2>/)
    expect(text(html)).toContain('Loading the run')
  })
})

describe('the side panel’s views', () => {
  it('shows Needs you as the sketch’s rows under Do now and Set up, every one the platform returned, with More details to Workflows', () => {
    const html = draw({ kind: 'needs' })
    expect(html).toMatch(/<h2[^>]*id="side-panel-h"[^>]*>Needs you<\/h2>/)
    expect(links(html)[0]).toEqual(['More details', '/workflows'])
    expect(text(html)).toMatch(/Do now[\s\S]*Software watchlist stopped[\s\S]*Set up/)
    expect(html.match(/data-home-item=/g)).toHaveLength(needsTotal(ALICE_HOME))
  })

  it('holds every request the strip’s N more counts: a page at a time with Show more, then all of them', () => {
    const [first] = BOB_HOME.approvals as [ApprovalItem]
    const asks = Array.from({ length: 27 }, (_, n) => ({ ...first, run_id: `run_${String(n)}`, approval_id: `apr_${String(n)}`, started_at: new Date(Date.UTC(2026, 10, 3, 1, 59 - n)).toISOString() }))
    const page = (from: number, to: number, next: string | null): NeedsPage => ({ ...EMPTY_PAGE, approvals: asks.slice(from, to), approvals_total: 27, next })
    const home: HomeOut = { ...BOB_HOME, ...page(0, 10, 'c1'), confirmations: [], needs_next: 'c1' }
    const strip = needsTotal(home)
    expect(strip, 'the strip counts every request').toBe(27)

    const firstPage = draw({ kind: 'needs' }, { me: BOB, home })
    expect(firstPage.match(/data-home-item=/g)).toHaveLength(10)
    expect(firstPage).toMatch(/role="status"[^>]*>Showing 10 of 27\.<\/p>/)
    expect(buttons(firstPage)).toContain('Show more')

    const all = draw({ kind: 'needs' }, { me: BOB, home, pages: [page(0, 10, 'c1'), page(10, 20, 'c2'), page(20, 27, null)] })
    expect([...all.matchAll(/data-home-item="approval:(apr_\d+)"/g)].map((m) => m[1])).toEqual(asks.map((ask) => ask.approval_id))
    expect(buttons(all)).not.toContain('Show more')
  })

  it('opens a row of Needs you in the panel, with a button that the chat’s Back can undo, and a page link where there is no panel item', () => {
    const html = draw({ kind: 'needs' }, { onOpen: OPEN_BESIDE })
    expect(html).toMatch(/<button[^>]*data-opens="run:run_01JB9"/)
    expect(html).toMatch(/<button[^>]*data-opens="software:sw_01JC2A3B4C5D6E7F8G9H0J1K2N"/)
    expect(html).toMatch(/<button[^>]*data-opens="connection:github"/)
  })

  it('shows Back, with the title of the item it returns to, only when there is one', () => {
    expect(buttons(draw({ kind: 'workflow', id: STOPPED.use_case_id }))).not.toContain('Needs you')
    const html = draw({ kind: 'workflow', id: STOPPED.use_case_id }, { back: { kind: 'needs' } })
    expect(buttons(html)).toEqual(['Needs you', 'Close', 'Retry', 'Pause'])
    expect(html.indexOf('Needs you')).toBeLessThan(html.indexOf('More details'))
  })

  it('lists every workflow, with its state and when it runs, each opening the workflow in the panel', () => {
    const html = draw({ kind: 'workflows' }, { onOpen: OPEN_BESIDE })
    expect(links(html)).toEqual([['More details', '/workflows']])
    expect(text(html)).toContain('1 workflow')
    expect(text(html)).toContain(`${STOPPED.name} `)
    expect(text(html)).toContain('Needs you')
    expect(html).toMatch(new RegExp(`<button[^>]*data-opens="workflow:${STOPPED.use_case_id}"`))
    expect(html, 'and an Explain beside each row, which opens the report in the panel too').toMatch(new RegExp(`<button[^>]*data-opens="explain:${STOPPED.use_case_id}"[^>]*>Explain`))
  })

  it('lists the watchlist with the Software page’s count line, each software’s versions and state', () => {
    const html = draw({ kind: 'watchlist' }, { onOpen: OPEN_BESIDE })
    const shown = text(html)
    expect(links(html)).toEqual([['More details', '/software']])
    expect(shown).toContain(countLine(WATCHLIST.software) ?? 'a count line')
    expect(shown).toContain('LangGraph 1.2.14 → 1.2.16 · checked by Software watchlist Newer out')
    expect(shown).toContain('n8n 2.42.6, the newest · checked by Software watchlist Up to date')
    expect(html.match(/data-opens="software:/g)).toHaveLength(WATCHLIST.software.length)
  })

  it('shows a connection’s real state in the platform’s words, with the key’s expiry in the pill, and sends the person to Settings', () => {
    const html = draw({ kind: 'connection', id: 'github' })
    expect(html).toMatch(/<h2[^>]*>GitHub key<\/h2>/)
    expect(text(html)).toContain('Connection')
    expect(text(html)).toContain('Expires Wed 18 Nov')
    expect(text(html)).toContain('The key runs out soon.')
    expect(text(html)).not.toContain('Asked the admin')
    expect(links(html)).toEqual([
      ['More details', '/settings?tab=connections'],
      ['See it in Settings', '/settings?tab=connections'],
    ])
  })

  it('says a connection that works again needs nothing, rather than showing what no longer holds', () => {
    const fixed: HomeOut = { ...ALICE_HOME, connections: [] }
    expect(text(draw({ kind: 'connection', id: 'github' }, { home: fixed }))).toContain('That connection doesn’t need anything from you now.')
  })

  it('keeps today’s run content for an approval, titled Approval until its run is read, with no page until then', () => {
    const html = draw({ kind: 'approval', id: 'run_01JBA' })
    expect(html).toMatch(/<h2[^>]*>Approval<\/h2>/)
    expect(html).toContain('data-panel="approval"')
    expect(text(html)).toContain('Loading the run')
    expect(links(html)).toEqual([])
  })

  it('gives the build view the wide mode and no page, and shows nothing it can’t do', () => {
    const html = draw({ kind: 'build', id: 'draft_1' })
    expect(html).toContain('data-wide="true"')
    expect(links(html)).toEqual([])
    expect(buttons(html)).toEqual(['Close'])
    expect(draw({ kind: 'needs' })).not.toContain('data-wide')
  })
})

describe('closing the side panel', () => {
  const ESCAPE = { key: 'Escape', defaultPrevented: false }

  it('closes on Escape', () => {
    expect(escapeIsFree(ESCAPE, false)).toBe(true)
    expect(escapeIsFree({ ...ESCAPE, key: 'Enter' }, false)).toBe(false)
  })

  it('leaves Escape to a dialog over it, such as Teams, or to an editor or menu inside that took it first', () => {
    expect(escapeIsFree(ESCAPE, true)).toBe(false)
    expect(escapeIsFree({ ...ESCAPE, defaultPrevented: true }, false)).toBe(false)
  })

  it('hands the focus it held back to the control that opened it, else another way to open the same item, else the box', () => {
    expect(focusAfterClose({ openers: ['card', 'pinned line'], from: 1, lost: true, box: 'box' })).toBe('pinned line')
    expect(focusAfterClose({ openers: ['card'], from: 1, lost: true, box: 'box' })).toBe('card')
    expect(focusAfterClose({ openers: [], from: 0, lost: true, box: 'box' })).toBe('box')
  })

  it('hands focus back to the control the person pressed, wherever focus has gone since', () => {
    expect(focusAfterClose({ openers: ['strip’s Open', 'card'], from: 1, lost: false, box: 'box' })).toBe('card')
  })

  it('leaves focus where it is when an answer showed the panel by itself, and sends what the panel held to the box, never to the first way to open it', () => {
    expect(focusAfterClose({ openers: ['strip’s Open', 'card'], from: null, lost: false, box: 'box' })).toBeNull()
    expect(focusAfterClose({ openers: ['strip’s Open', 'card'], from: null, lost: true, box: 'box' })).toBe('box')
  })
})

describe('Tab in a panel that covers the window', () => {
  const STOPS = ['More details', 'Close', 'Retry the run'] as const

  it('goes round from the last stop to the first, and back', () => {
    expect(wrapTab(STOPS, 'Retry the run', false)).toBe('More details')
    expect(wrapTab(STOPS, 'More details', true)).toBe('Retry the run')
  })

  it('moves as usual between stops inside it', () => {
    expect(wrapTab(STOPS, 'Close', false)).toBeNull()
    expect(wrapTab(STOPS, 'Close', true)).toBeNull()
  })

  it('comes back inside from its heading, which focus reaches but Tab does not', () => {
    expect(wrapTab(STOPS, 'heading', false)).toBe('More details')
    expect(wrapTab(STOPS, 'heading', true)).toBe('Retry the run')
  })
})
