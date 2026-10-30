import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { HomeOut, StoppedItem } from '../../api/types'
import { needsOf, type Need } from './home'
import { DraftRow, NeedItem, WaitingRow, type Motion } from './HomeItem'

const NOW = new Date('2026-11-04T15:00:00+08:00')
const STILL: Motion = { arrive: false, index: 0, leaving: false, onGone: () => undefined }
const [ASK] = needsOf(bobHome as HomeOut).shown as [Need]
const [STOPPED] = needsOf(aliceHome as HomeOut).shown as [Need]
const ALICE = aliceHome as HomeOut

function render(node: ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <ul>{node}</ul>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const controls = (html: string) => [...html.matchAll(/<(a|button)\b([^>]*)>([\s\S]*?)<\/\1>/g)].map((m) => ({ tag: m[1], attrs: m[2] ?? '', name: text(m[3] ?? '') }))

describe('a row after the card', () => {
  it('keeps only its first button, not the main one, and names it by the row’s title', () => {
    const html = render(<NeedItem need={STOPPED} card={false} now={NOW} motion={STILL} />)
    const [only, ...rest] = controls(html)
    expect(rest).toEqual([])
    expect(only?.name).toBe('Retry the run')
    expect(only?.attrs).not.toMatch(/_primary_/)
    const described = /aria-describedby="([^"]+)"/.exec(only?.attrs ?? '')?.[1]
    expect(html).toMatch(new RegExp(`<b id="${described}">Software watchlist stopped</b>`))
  })

  it('carries the AI troubleshooter’s reason on the row itself', () => {
    expect(text(render(<NeedItem need={STOPPED} card={false} now={NOW} motion={STILL} />))).toContain(
      'AI troubleshooter: An agent could not finish its work. Retry the run.',
    )
  })
})

describe('the card', () => {
  it('opens a run that cannot be retried, as its main button', () => {
    const final = { ...STOPPED, item: { ...(STOPPED.item as StoppedItem), retryable: false } } as Need
    const [only, ...rest] = controls(render(<NeedItem need={final} card now={NOW} motion={STILL} />))
    expect(rest).toEqual([])
    expect(only).toMatchObject({ tag: 'a', name: 'See why it stopped' })
    expect(only?.attrs).toMatch(/_primary_/)
  })
})

describe('an item that is leaving', () => {
  it('is hidden from assistive technology and cannot be used while it fades', () => {
    const html = render(<NeedItem need={ASK} card now={NOW} motion={{ ...STILL, leaving: true }} />)
    expect(html).toMatch(/<li[^>]*aria-hidden="true"[^>]*inert=""/)
    expect(html).toMatch(/class="[^"]*_leaving_/)
  })

  it('arrives in its place in the first paint, and not at all when the person came back', () => {
    const arriving = render(<WaitingRow item={ALICE.waiting_on_others[0]!} now={NOW} motion={{ ...STILL, arrive: true, index: 2 }} />)
    expect(arriving).toMatch(/<li class="[^"]*_arrive_[^"]*"[^>]*style="--i:2"/)
    expect(render(<DraftRow draft={ALICE.drafts[0]!} now={NOW} arrive={false} index={0} />)).not.toMatch(/_arrive_/)
  })
})
