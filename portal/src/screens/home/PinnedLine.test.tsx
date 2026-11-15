import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import dayOne from '../../../../contracts/fixtures/builder/home.day-one.json'
import type { HomeOut } from '../../api/types'
import { OpensInPanel, type PanelItem } from '../../ui/sidePanel'
import { needsTotal } from './home'
import { PinnedLine } from './PinnedLine'

const NOW = new Date('2026-11-03T15:00:00+08:00')
const ALICE = aliceHome as HomeOut
const BOB = bobHome as HomeOut

const draw = (home: HomeOut) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PinnedLine home={home} now={NOW} />
    </MemoryRouter>,
  )
const inChat = (home: HomeOut, shown: PanelItem | null) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <OpensInPanel.Provider value={{ shown, open: () => undefined, show: () => undefined }}>
        <PinnedLine home={home} now={NOW} />
      </OpensInPanel.Provider>
    </MemoryRouter>,
  )
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttonsOf = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [text(m[2] ?? ''), m[1]])

describe('the needs strip', () => {
  it('is the region “Needs you”, tinted by the most urgent need, and names it in its short form', () => {
    const html = draw(ALICE)
    expect(html).toMatch(/<section[^>]*aria-label="Needs you"[^>]*data-tone="err"/)
    expect(html).toContain('<b>Software watchlist</b> stopped')
    expect(text(html)).not.toContain('An agent could not finish its work.')
    expect(draw(BOB)).toMatch(/data-tone="wait"/)
  })

  it('offers Open, to the item’s own page, and “N more” to Workflows, the two with Back to the chat', () => {
    const html = draw(ALICE)
    expect(links(html)).toEqual([
      [`${String(needsTotal(ALICE) - 1)} more that need you`, '/workflows'],
      ['Open : Software watchlist stopped', '/runs/run_01JB9'],
    ])
  })

  it('counts so that N more plus the one it names is the total every other place shows', () => {
    for (const home of [ALICE, BOB]) {
      const more = /(\d+) more/.exec(text(draw(home)))?.[1]
      expect(Number(more) + 1).toBe(needsTotal(home))
    }
  })

  it('has no “N more” when the one it names is all there is', () => {
    const one: HomeOut = { ...BOB, confirmations: [] }
    expect(needsTotal(one)).toBe(1)
    expect(text(draw(one))).not.toContain('more')
    expect(links(draw(one))).toEqual([['Open : Software watchlist needs your yes', '/runs/run_01JB8']])
  })

  it('stays when nothing needs the person, calm, and says so with nothing to open', () => {
    const html = draw(dayOne)
    expect(html).toMatch(/<section[^>]*aria-label="Needs you"[^>]*data-tone="calm"/)
    expect(text(html)).toBe('Nothing needs you')
    expect(links(html)).toEqual([])
  })

  it('has one button, and it is not the main one, because the newest answer has that', () => {
    expect((draw(ALICE).match(/_primary_/g) ?? []).length).toBe(0)
  })

  it('in the chat opens a stop in the side panel, and gives way while the panel shows it', () => {
    expect(inChat(ALICE, null)).toMatch(/<button[^>]*data-opens="run:run_01JB9"[^>]*>Open/)
    expect(links(inChat(ALICE, null))).toEqual([])
    expect(text(inChat(ALICE, { kind: 'run', id: 'run_01JB9' }))).not.toContain('Open')
    expect(inChat(ALICE, { kind: 'run', id: 'run_other' })).toContain('data-opens="run:run_01JB9"')
  })

  it('in the chat opens the rest of Needs you in the side panel, and keeps its words while the panel shows them', () => {
    const more = `${String(needsTotal(ALICE) - 1)} more that need you`
    for (const shown of [null, { kind: 'needs' } as const]) {
      const html = inChat(ALICE, shown)
      expect(html).toMatch(/<button[^>]*data-opens="needs:"[^>]*>/)
      expect(buttonsOf(html)).toContain(more)
    }
  })

  it('opens a request as an approval in the side panel', () => {
    expect(inChat(BOB, null)).toMatch(/<button[^>]*data-opens="approval:run_01JB8"[^>]*>Open/)
  })
})
