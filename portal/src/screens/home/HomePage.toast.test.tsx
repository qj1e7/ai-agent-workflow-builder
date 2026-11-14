/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { HomeOut, Me } from '../../api/types'
import toastStyles from '../../ui/Toast.module.css'
import { ChatProvider } from './ChatProvider'
import { desksReducer, type Desks } from './chatState'
import { HomePage } from './HomePage'
import planner from './Planner.module.css'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const NOTE = 'Back to version 2, saved as version 4.'
const noted = (desks: Desks): Desks => desksReducer(desks, { user: 'alice', action: { type: 'note', text: NOTE } })
const IN_CHAT = noted(
  desksReducer(
    desksReducer({}, { user: 'alice', action: { type: 'sent', text: 'What can you do?' } }),
    { user: 'alice', action: { type: 'answered', reply: { answer: 'abilities', parts: [] }, typed: 'What can you do?' } },
  ),
)
const ON_HOME = noted({})

function draw(desks: Desks): string {
  const session = createDevSession({ getItem: () => ALICE.id, setItem: () => undefined })
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], ALICE)
  queryClient.setQueryData<HomeOut>(['home', scope], aliceHome as HomeOut)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <ChatProvider initial={desks}>
            <HomePage greeting="Good afternoon, Alice" today="Tuesday 3 November." now={new Date('2026-11-03T15:00:00+08:00')} />
          </ChatProvider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

/** The bodies of the rules in a CSS file whose selector names the class. */
const rulesOf = (css: string, name: string): string[] => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((rule) => new RegExp(`\\.${name}\\b`).test(rule[1] ?? '')).map((rule) => rule[2] ?? '')

describe('Home’s toast', () => {
  it.each([
    ['on Home before the first message', ON_HOME],
    ['in the chat', IN_CHAT],
  ])('sits in the dock above the box %s, so it never covers the box, the chips or a card’s buttons', (_, desks) => {
    const html = draw(desks)
    const dock = html.indexOf(`<div class="${planner['dock'] ?? ''}">`)
    const toast = html.indexOf(`aria-hidden="true">${NOTE}</span>`)
    const box = html.indexOf('id="planner-box"')
    expect(dock, 'the dock is drawn').toBeGreaterThanOrEqual(0)
    expect(toast, 'the toast says the note').toBeGreaterThan(dock)
    expect(box, 'the toast comes before the box, inside the dock').toBeGreaterThan(toast)
    expect(html, 'Home never floats the toast at the foot of the page').not.toContain(`class="${toastStyles['dock'] ?? ''}"`)
  })

  it('is placed by the dock’s own flow, never positioned over it', () => {
    const css = readFileSync(new URL('../../ui/Toast.module.css', import.meta.url), 'utf8')
    const inline = rulesOf(css, 'inline')
    expect(inline.length, 'the in-flow toast has its own rules').toBeGreaterThan(0)
    for (const body of inline) expect(body, 'no rule lifts the in-flow toast out of the dock').not.toMatch(/\b(position|top|bottom|left|right|inset|transform)\s*:/)
  })
})
