import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import stopped from '../../../../contracts/fixtures/builder/use-case.stopped.json'
import advice from '../../../../contracts/fixtures/troubleshooting/failure.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { CapabilitiesView, Me, UseCaseView, WatchlistView } from '../../api/types'
import { InChat } from '../../ui/fromChat'
import { escapeIsFree } from '../../ui/escape'
import { openerAfterClose, wrapTab, type PanelItem } from '../../ui/sidePanel'
import { SidePanel } from './SidePanel'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const NOW = new Date('2026-11-05T15:00:00+08:00')
const STOPPED = stopped as UseCaseView
const WATCHLIST = statuses as WatchlistView
const REDIS = 'sw_01JBW00000000000000000003'
const REGISTRY = capabilities as CapabilitiesView
const GITHUB_DOWN: CapabilitiesView = { ...REGISTRY, capabilities: REGISTRY.capabilities.map((c) => (c.id === 'github.releases' ? { ...c, state: 'down' as const } : c)) }

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))
const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((match) => [text(match[2] ?? ''), match[1]])

function draw(item: PanelItem, { me = ALICE, narrow = false, useCase = STOPPED, registry = REGISTRY }: { me?: Me; narrow?: boolean; useCase?: UseCaseView; registry?: CapabilitiesView } = {}): string {
  const session = createDevSession({ getItem: () => me.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['watchlist', scope], WATCHLIST)
  queryClient.setQueryData(['capabilities', scope], registry)
  queryClient.setQueryData(['use-case', scope, useCase.use_case_id], useCase)
  queryClient.setQueryData(['troubleshoot', scope, STOPPED.last_run?.run_id, 0], advice)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <InChat.Provider value>
            <SidePanel item={item} now={NOW} narrow={narrow} onClose={() => undefined} />
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
    expect(links(html)).toEqual([['More details', `/software?row=${REDIS}`]])
    expect(buttons(html)).toEqual(['Close'])
  })

  it('sits beside the chat as a region, and covers a narrow window as a dialog', () => {
    expect(draw({ kind: 'software', id: REDIS })).toMatch(/role="complementary"[^>]*aria-labelledby="side-panel-h"/)
    expect(draw({ kind: 'software', id: REDIS }, { narrow: true })).toMatch(/role="dialog" aria-modal="true" aria-labelledby="side-panel-h"/)
  })

  it('shows a software’s status, the version you run, the newest, and what checks it and when, in the Software page’s words', () => {
    const shown = text(draw({ kind: 'software', id: REDIS }))
    expect(shown).toContain('Ticket waiting for a yes')
    expect(shown).toContain('You run Not known')
    expect(shown).toContain('Newest 8.2.1')
    expect(shown).toContain('Checked by The Version checker, on GitHub.')
    expect(shown).toContain('When Checked every Monday at 9:00, set by Alice. Next check')
  })

  it('says so when GitHub isn’t working, as the capability registry says, and never claims a check that can’t run', () => {
    const shown = text(draw({ kind: 'software', id: REDIS }, { registry: GITHUB_DOWN }))
    expect(shown).toContain('Checked by The Version checker, on GitHub, which is not working right now.')
  })

  it('says an item that has gone is gone, with no More details', () => {
    const html = draw({ kind: 'software', id: 'sw_gone' })
    expect(text(html)).toContain('That software isn’t on the Software watchlist any more.')
    expect(links(html)).toEqual([])
  })

  it('shows a stopped workflow’s three answers with Retry, its last and next run, Open the run, and Pause, to an Operator', () => {
    const html = draw({ kind: 'workflow', id: STOPPED.use_case_id })
    const shown = text(html)
    expect(shown).toMatch(/What happened[\s\S]*What was affected[\s\S]*Safe to retry[\s\S]*Last run[\s\S]*Next run/)
    expect(buttons(html)).toEqual(['Close', 'Retry the run', 'Pause'])
    expect(links(html)).toEqual([
      ['More details', `/workflows/${STOPPED.use_case_id}`],
      ['Open the run', `/runs/${STOPPED.last_run?.run_id ?? ''}`],
    ])
  })

  it('gives an Approver who isn’t an Operator the same answers, and no control he can’t use', () => {
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

  it('hands focus back to the control that opened it, else another way to open the same item', () => {
    expect(openerAfterClose(['card', 'pinned line'], 1)).toBe('pinned line')
    expect(openerAfterClose(['card'], 1)).toBe('card')
    expect(openerAfterClose([], 0)).toBeNull()
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
