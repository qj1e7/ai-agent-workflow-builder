import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import type { HomeOut } from '../../api/types'
import { needsOf } from './home'
import { NeedRows } from './NeedsSection'

const NOW = new Date('2026-11-04T15:00:00+08:00')
const needs = needsOf(aliceHome as unknown as HomeOut).shown
const draw = (tiles: boolean) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <NeedRows needs={needs} now={NOW} more={null} tiles={tiles} {...(tiles ? { level: 3 as const } : {})} />
    </MemoryRouter>,
  )

describe('Needs you’s two looks', () => {
  it('keeps the compact rows in the chat’s card and the side panel: level 2 group labels, a small dot, no tile mark', () => {
    const html = draw(false)
    expect(html).toMatch(/<h2 id="[^"]*">Do now<\/h2>/)
    expect(html).not.toMatch(/_tiles_|_mark_/)
    expect(html).toMatch(/_dot_/)
  })

  it('draws bright tiles with a mark on Home and Workflows, under level 3 group labels', () => {
    const html = draw(true)
    expect(html).toMatch(/<h3 id="[^"]*">Do now<\/h3>/)
    expect(html).toMatch(/_tiles_/)
    expect(html).toMatch(/_mark_/)
    expect(html).not.toMatch(/_dot_/)
  })
})
