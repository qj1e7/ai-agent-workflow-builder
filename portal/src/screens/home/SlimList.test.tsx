import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import watchlist from '../../../../contracts/fixtures/builder/use-case.json'
import type { UseCaseView } from '../../api/types'
import type { StepDraw } from '../../ui/StepLine'
import { boardOf } from './boardTiles'
import { SlimList } from './SlimList'

const NOW = new Date('2026-11-27T01:00:00Z')
const base = watchlist as unknown as UseCaseView
const made = (id: string, over: Partial<UseCaseView> = {}): UseCaseView => ({ ...base, use_case_id: id, name: `Workflow ${id}`, last_run: null, needs_you: null, next_run_at: '2026-11-30T01:00:00Z', ...over })
const STEPS: StepDraw[] = [
  { key: 'a', name: 'Read versions', icon: 'read', state: 'done' },
  { key: 'b', name: 'Ask for approval', icon: 'gate', state: 'wait' },
]

const draw = (useCases: UseCaseView[], over: { needs?: number; operator?: boolean; steps?: Map<string, readonly StepDraw[]> } = {}) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <SlimList board={boardOf(useCases, NOW)} steps={over.steps ?? new Map()} needs={over.needs ?? 0} operator={over.operator ?? true} />
    </MemoryRouter>,
  )

describe('the slim list beside the chat', () => {
  it('is one list named like the board, with a row per workflow: its name and its one pill', () => {
    const html = draw([made('a'), made('b', { state: 'paused' })])
    expect(html).toContain('aria-label="Your workflows"')
    expect(html.match(/<li/g)).toHaveLength(2)
    expect(html.match(/data-tone="/g)).toHaveLength(2)
    expect(html).toContain('Workflow a')
  })

  it('is named Workflows for someone who only approves', () => {
    expect(draw([made('a')], { operator: false })).toContain('aria-label="Workflows"')
  })

  it('draws the small step line for a run that could be read, and no line for one that could not', () => {
    const html = draw([made('a'), made('b')], { steps: new Map([['a', STEPS]]) })
    expect(html.match(/role="img"/g)).toHaveLength(1)
    expect(html).toContain('aria-label="Last run: Done: Read versions, Waiting for approval: Ask for approval"')
  })

  it('says nothing about next runs or last runs: the board has those', () => {
    const html = draw([made('a', { state: 'on' })])
    expect(html).not.toMatch(/Next run|Last run|No runs yet/)
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
