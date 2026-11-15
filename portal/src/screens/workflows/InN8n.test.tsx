import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import held from '../../../../contracts/fixtures/builder/use-case.n8n.held.json'
import free from '../../../../contracts/fixtures/builder/use-case.n8n.json'
import turnedOn from '../../../../contracts/fixtures/builder/use-case.turned-on.json'
import peopleList from '../../../../contracts/fixtures/people/list.json'
import { App } from '../../App'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PersonOut, UseCaseN8nView, UseCaseView } from '../../api/types'
import { DRAFT, SAFE_BLOCKS } from './n8nHold'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator'], n8n_access: true }
const CAROL: Me = { id: 'carol', display: 'Carol', roles: ['operator'], n8n_access: true }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob', 'carol'].includes(person.id))
const ON = turnedOn as UseCaseView
const FREE = free as UseCaseN8nView
const HELD = held as UseCaseN8nView
/** 17:00 in Singapore, on the day Carol opened it at 13:40. */
const NOW = new Date('2026-11-10T09:00:00Z')

interface Setup {
  readonly me?: Me
  readonly view?: UseCaseN8nView | null
  readonly useCase?: UseCaseView
  readonly path?: string
}

function render({ me = ALICE, view = FREE, useCase = ON, path = `/workflows/${ON.use_case_id}?view=n8n` }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB, CAROL])
  queryClient.setQueryData(['people', scope], TEAM)
  queryClient.setQueryData(['runs', scope], [])
  queryClient.setQueryData(['use-case', scope, useCase.use_case_id], useCase)
  if (view) queryClient.setQueryData(['use-case', scope, useCase.use_case_id, 'n8n'], view)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const main = (html: string) => /<main[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
const buttons = (html: string) => [...main(html).matchAll(/<(?:button|a)\b[^>]*class="[^"]*_button_[^"]*"[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const primaries = (html: string) => (main(html).match(/class="[^"]*_primary_[^"]*"/g) ?? []).length
const tabs = (html: string) => [...main(html).matchAll(/<button type="button" aria-pressed="(true|false)">([^<]*)<\/button>/g)].map((m) => `${m[2] ?? ''}${m[1] === 'true' ? ' (shown)' : ''}`)
const OPEN = 'Open in n8n editor (opens in a new tab)'

describe('the workflow page’s Summary and In n8n tabs', () => {
  it('shows the two tabs only to someone with n8n access, on Summary unless the address asks for In n8n', () => {
    expect(tabs(render({ path: `/workflows/${ON.use_case_id}` }))).toEqual(['Summary (shown)', 'In n8n'])
    expect(tabs(render())).toEqual(['Summary', 'In n8n (shown)'])
    const bob = render({ me: BOB })
    expect(tabs(bob), 'an Approver never has n8n access').toEqual([])
    expect(text(main(bob)), 'and the address can’t open the tab for him').not.toContain(SAFE_BLOCKS)
    expect(tabs(render({ me: { ...ALICE, n8n_access: false } }))).toEqual([])
  })

  it('offers Open in n8n editor beside Pause on Summary too, as the sketch does', () => {
    const html = render({ path: `/workflows/${ON.use_case_id}` })
    expect(buttons(html)).toContain(OPEN)
    expect(buttons(render({ me: { ...ALICE, n8n_access: false }, path: `/workflows/${ON.use_case_id}` }))).not.toContain(OPEN)
  })
})

describe('the In n8n tab', () => {
  it('shows the version in use, the safe-blocks line, the canvas and Open in n8n editor as the one main button', () => {
    const html = render()
    expect(text(main(html))).toContain('Version 1, published by Carol, ')
    expect(text(main(html))).toContain(SAFE_BLOCKS)
    expect(main(html)).toContain('<title')
    expect(text(main(html))).toContain('LangGraph release check in n8n: Mon 8:00, Start from the Portal, Read release')
    expect(buttons(html)).toEqual([OPEN])
    expect(primaries(html)).toBe(1)
    expect(text(main(html))).not.toMatch(/has it open/)
  })

  it('tells someone else who has it open, that anyone with n8n access may take it back, and draws no Open', () => {
    const html = render({ view: { ...HELD, editor_url: null } })
    expect(text(main(html))).toContain('Carol has it open in n8n since 13:40.')
    expect(text(main(html))).toContain('Anyone with n8n access can take it back from Carol.')
    expect(buttons(html)).toEqual(['Take it back'])
    expect(primaries(html)).toBe(0)
  })

  it('says why someone whose n8n is not ready can’t take it back, and draws no button', () => {
    const html = render({ view: { ...HELD, editor_url: null, can_open: false, why_not: 'Set your n8n password first. The link is on your Settings page.' } })
    expect(text(main(html))).toContain('Carol has it open in n8n since 13:40. Set your n8n password first.')
    expect(buttons(html)).toEqual([])
  })

  it('gives its holder a plain link to the editor, and Take it back', () => {
    const html = render({ me: CAROL, view: HELD })
    expect(text(main(html))).toContain('You have it open in n8n since 13:40.')
    expect(buttons(html)).toEqual(['Take it back', OPEN])
    expect(main(html)).toMatch(new RegExp(`<a href="${HELD.editor_url ?? ''}"[^>]*target="_blank" rel="noopener noreferrer"`))
  })

  it('says a draft must be turned on first, with no button that would be refused', () => {
    const html = render({ useCase: { ...ON, state: 'draft' } })
    expect(text(main(html))).toContain('Version 1, saved as a draft by Carol')
    expect(text(main(html))).toContain(DRAFT)
    expect(buttons(html)).toEqual([])
  })

  it('says it is loading until the platform answers', () => {
    expect(text(main(render({ view: null })))).toContain('Loading the workflow in n8n')
  })
})
