import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { readFileSync } from 'node:fs'
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
import { TakeItBackHere } from './InN8n'
import { DRAFT, NOT_LOADED, opensInN8nAs, SAFE_BLOCKS } from './n8nHold'

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
  readonly view?: UseCaseN8nView | null | Error
  readonly useCase?: UseCaseView
  readonly path?: string
  /** What `/me/n8n` says the n8n login is. Left out, the read has not come back. */
  readonly login?: string | null
}

function render({ me = ALICE, view = FREE, useCase = ON, path = `/workflows/${ON.use_case_id}?view=n8n`, login }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  if (login !== undefined) queryClient.setQueryData(['n8n-login', scope], login)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB, CAROL])
  queryClient.setQueryData(['people', scope], TEAM)
  queryClient.setQueryData(['runs', scope], [])
  // The platform says who holds it on the workflow and on its In n8n view alike.
  const answered = view instanceof Error ? null : view
  queryClient.setQueryData(['use-case', scope, useCase.use_case_id], { ...useCase, held_in_n8n: answered?.holder ?? useCase.held_in_n8n ?? null })
  const viewKey = ['use-case', scope, useCase.use_case_id, 'n8n']
  if (view instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: viewKey }).setState({ status: 'error', error: view, fetchStatus: 'idle' })
  else if (view) queryClient.setQueryData(viewKey, view)
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
    expect(text(main(bob)), 'and the address can’t open the tab for them').not.toContain(SAFE_BLOCKS)
    expect(tabs(render({ me: { ...ALICE, n8n_access: false } }))).toEqual([])
  })

  it('says on Summary who has it open in n8n, in place of the Open in n8n editor that would be refused', () => {
    const html = render({ view: { ...HELD, editor_url: null }, path: `/workflows/${ON.use_case_id}` })
    expect(text(main(html))).toContain('Carol has it open in n8n since 13:40.')
    expect(buttons(html)).not.toContain(OPEN)
  })

  it('says on Summary who has it open, with Take it back only once the In n8n view says the platform would allow it', () => {
    const summary = `/workflows/${ON.use_case_id}`
    const loading = render({ view: null, useCase: { ...ON, held_in_n8n: HELD.holder }, path: summary })
    expect(text(main(loading))).toContain('Carol has it open in n8n since 13:40.')
    expect(text(main(loading))).not.toContain('can take it back')
    expect(buttons(loading)).not.toContain('Take it back')
    expect(buttons(render({ view: { ...HELD, editor_url: null }, path: summary }))).toContain('Take it back')
    const refused = render({ view: { ...HELD, editor_url: null, can_open: false, why_not: 'Set your n8n password first.' }, path: summary })
    expect(text(main(refused))).toContain('Set your n8n password first.')
    expect(buttons(refused)).not.toContain('Take it back')
    const failed = render({ view: new Error('offline'), useCase: { ...ON, held_in_n8n: HELD.holder }, path: summary })
    expect(text(main(failed))).toContain(`Carol has it open in n8n since 13:40. ${NOT_LOADED}`)
    expect(buttons(failed)).not.toContain('Take it back')
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

describe('Take it back on a refused change', () => {
  function drawTakeBack(me: Me, view: UseCaseN8nView, refused = true, answer: 'loaded' | 'loading' | Error = 'loaded'): string {
    const session = createDevSession(null)
    const scope = session.cacheScope()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
    queryClient.setQueryData(['me', scope], me)
    queryClient.setQueryData(['use-case', scope, ON.use_case_id], { ...ON, held_in_n8n: view.holder })
    const viewKey = ['use-case', scope, ON.use_case_id, 'n8n']
    if (answer instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: viewKey }).setState({ status: 'error', error: answer, fetchStatus: 'idle' })
    else if (answer === 'loaded') queryClient.setQueryData(viewKey, view)
    return renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
          <TakeItBackHere useCaseId={ON.use_case_id} refused={refused} say={() => undefined} />
        </ApiProvider>
      </QueryClientProvider>,
    )
  }
  const all = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

  it('offers Take it back to someone who may take it back, once the platform refused the change', () => {
    expect(all(drawTakeBack(ALICE, { ...HELD, editor_url: null }))).toEqual(['Take it back'])
    expect(all(drawTakeBack(CAROL, HELD)), 'its holder too').toEqual(['Take it back'])
  })

  it('offers nothing while the In n8n view that says whether the platform would allow it is loading', () => {
    expect(all(drawTakeBack(ALICE, { ...HELD, editor_url: null }, true, 'loading'))).toEqual([])
  })

  it('says why it offers nothing when the In n8n view could not be read', () => {
    const html = drawTakeBack(ALICE, { ...HELD, editor_url: null }, true, new Error('offline'))
    expect(all(html)).toEqual([])
    expect(text(html)).toBe(NOT_LOADED)
  })

  it('offers nothing before a refusal, to someone without n8n access, or while nobody holds it', () => {
    expect(all(drawTakeBack(ALICE, { ...HELD, editor_url: null }, false))).toEqual([])
    expect(all(drawTakeBack({ ...ALICE, n8n_access: false }, { ...HELD, editor_url: null }))).toEqual([])
    expect(all(drawTakeBack(ALICE, FREE))).toEqual([])
    expect(all(drawTakeBack(ALICE, { ...HELD, editor_url: null, can_open: false, why_not: 'Set your n8n password first.' }))).toEqual([])
  })
})

describe('the n8n login under Open in n8n editor', () => {
  const LOGIN = 'dana.n8ntest@example.test'
  const SENTENCE = `Opens in n8n as ${LOGIN}.`
  const hint = (html: string) => [...main(html).matchAll(/<p class="[^"]*_hint_[^"]*"[^>]*data-n8n-hint[^>]*>([\s\S]*?)<\/p>/g)].map((m) => text(m[1] ?? ''))
  const summary = `/workflows/${ON.use_case_id}`

  it('is one sentence, kept beside the button’s own words', () => {
    expect(opensInN8nAs(LOGIN)).toBe(SENTENCE)
  })

  it('shows the exact sentence under the press button on the In n8n tab and on Summary', () => {
    expect(hint(render({ login: LOGIN }))).toEqual([SENTENCE])
    expect(hint(render({ login: LOGIN, path: summary }))).toEqual([SENTENCE])
  })

  it('shows it under the plain link too, when the person already holds the workflow', () => {
    const html = render({ me: CAROL, view: HELD, login: LOGIN })
    expect(buttons(html)).toEqual(['Take it back', OPEN])
    expect(hint(html)).toEqual([SENTENCE])
  })

  it('draws no line, and no half sentence, while the login is unknown, still loading or failed to load', () => {
    for (const html of [render(), render({ login: null }), render({ login: '' })]) {
      expect(buttons(html)).toEqual([OPEN])
      expect(hint(html)).toEqual([])
      expect(text(main(html))).not.toMatch(/Opens in n8n as|as null/)
    }
  })

  it('draws no line where there is no button', () => {
    const html = render({ login: LOGIN, useCase: { ...ON, state: 'draft' } })
    expect(buttons(html)).toEqual([])
    expect(hint(html)).toEqual([])
  })

  it('wraps a long email inside its box, in the quiet small text', () => {
    const long = `${'a-very-long-name-with-no-break.'.repeat(6)}n8ntest@example.test`
    const html = render({ login: long })
    expect(hint(html)).toEqual([`Opens in n8n as ${long}.`])
    const css = readFileSync(new URL('./N8nLoginHint.module.css', import.meta.url), 'utf8')
    expect(css).toMatch(/\.hint\s*{[^}]*overflow-wrap:\s*anywhere/)
    expect(css).toMatch(/\.wrap\s*{[^}]*min-width:\s*0/)
  })
})
