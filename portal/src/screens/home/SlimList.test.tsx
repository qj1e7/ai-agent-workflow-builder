import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import watchlist from '../../../../contracts/fixtures/builder/use-case.json'
import type { UseCaseView } from '../../api/types'
import { boardOf } from './boardTiles'
import { SlimList } from './SlimList'

const NOW = new Date('2026-11-27T01:00:00Z')
const base = watchlist as unknown as UseCaseView
const made = (id: string, over: Partial<UseCaseView> = {}): UseCaseView => ({ ...base, use_case_id: id, name: `Workflow ${id}`, last_run: null, needs_you: null, next_run_at: '2026-11-30T01:00:00Z', ...over })
const draw = (useCases: UseCaseView[], over: { needs?: number; operator?: boolean } = {}) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <SlimList board={boardOf(useCases, NOW)} needs={over.needs ?? 0} operator={over.operator ?? true} />
    </MemoryRouter>,
  )

describe('the slim list beside the chat', () => {
  it('is one landmark for the glance, with a list named like the board and a row per workflow: a state mark and its name', () => {
    const html = draw([made('a'), made('b', { state: 'paused' })])
    expect(html).toContain('aria-label="Needs you and your workflows"')
    expect(html).toMatch(/<ul[^>]*aria-label="Your workflows"/)
    expect(html.match(/<li/g)).toHaveLength(2)
    expect(html).toContain('Workflow a')
  })

  it('names the list Workflows for someone who only approves', () => {
    expect(draw([made('a')], { operator: false })).toMatch(/<ul[^>]*aria-label="Workflows"/)
  })

  it('says each state with a mark that is one picture with the pill’s words, and no pill, no step line and no words of its own', () => {
    const html = draw([made('a', { needs_you: 'stopped' }), made('b', { state: 'paused' }), made('c', { state: 'draft' }), made('d', { state: 'on' })])
    expect([...html.matchAll(/role="img"[^>]*aria-label="([^"]*)"/g)].map((m) => m[1])).toEqual(['Needs you', 'Paused', 'Draft', 'On'])
    expect(html).not.toContain('data-tone=')
    expect(html).not.toMatch(/Last run|Next run|No runs yet/)
  })

  it('shows the Needs you count first, as a link that opens Needs you when something needs the person', () => {
    const html = draw([made('a')], { needs: 3 })
    expect(html.indexOf('Needs you')).toBeLessThan(html.indexOf('Workflow a'))
    expect(html).toMatch(/<a[^>]*href="\/workflows"[^>]*>Needs you <span[^>]*>3<\/span><\/a>/)
  })

  it('shows the count as plain text, not a control, when nothing needs the person', () => {
    const html = draw([made('a')], { needs: 0 })
    expect(html).toMatch(/<p[^>]*>Needs you <span[^>]*>0<\/span><\/p>/)
    expect(html).not.toMatch(/<a[^>]*>Needs you/)
  })

  it('ends with See all, to Workflows', () => {
    expect(draw([made('a')])).toMatch(/<a[^>]*href="\/workflows"[^>]*>See all<\/a>/)
  })

  it('draws no list of workflows before there are any, and keeps the count', () => {
    const html = draw([], { needs: 2 })
    expect(html).not.toContain('<ul')
    expect(html).toContain('Needs you')
  })
})
