import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import watchlist from '../../../../contracts/fixtures/builder/use-case.json'
import type { UseCaseView } from '../../api/types'
import type { StepDraw } from '../../ui/StepLine'
import { Board, NextUp } from './Board'
import { BOARD_SHOWN, boardOf } from './boardTiles'

const NOW = new Date('2026-11-27T01:00:00Z')
const base = watchlist as unknown as UseCaseView
const made = (id: string, over: Partial<UseCaseView> = {}): UseCaseView => ({ ...base, use_case_id: id, name: `Workflow ${id}`, last_run: null, needs_you: null, next_run_at: '2026-11-30T01:00:00Z', ...over })
const lastRun = (state: string, over: object = {}) =>
  ({ run_id: 'run_1', state, at: '2026-11-27T00:00:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: true, you_can_decide: false, you_can_open: false, retryable: false, reason: null, stop: null, outcome: 'nothing_to_write', ...over }) as UseCaseView['last_run']
const STEPS: StepDraw[] = [
  { key: 'a', name: 'Read versions', icon: 'read', state: 'done' },
  { key: 'b', name: 'Ask for approval', icon: 'gate', state: 'wait' },
]

const draw = (useCases: UseCaseView[], steps = new Map<string, readonly StepDraw[]>(), heading = 'Your workflows') =>
  renderToStaticMarkup(
    <MemoryRouter>
      <Board board={boardOf(useCases, NOW)} steps={steps} now={NOW} heading={heading} nameOf={(id) => id} />
    </MemoryRouter>,
  )

describe('Home’s board', () => {
  it('draws a tile per workflow, each one link with its name, its one pill and its next run', () => {
    const html = draw([made('a'), made('b', { state: 'paused' })])
    expect(html.match(/<li/g)).toHaveLength(2)
    expect(html.match(/data-tone="/g)).toHaveLength(2)
    expect(html).toContain('Workflow a')
    expect(html).toContain('Next run')
    expect(html.match(/Next run/g)).toHaveLength(1)
  })

  it('draws the last run as the shared step line when it could be read, and then says only when it was', () => {
    const html = draw([made('a', { last_run: lastRun('awaiting_approval') })], new Map([['a', STEPS]]))
    expect(html).toContain('role="img"')
    expect(html).toContain('aria-label="Last run: Done: Read versions, Waiting for approval: Ask for approval"')
    expect(html).not.toMatch(/nothing new/i)
  })

  it('draws no line, and no dots, when the run could not be read, and then says how the run went', () => {
    const html = draw([made('a', { last_run: lastRun('succeeded') })])
    expect(html).not.toContain('role="img"')
    expect(html).toMatch(/Today 8:00/)
    expect(html).toMatch(/nothing new/i)
  })

  it('says No runs yet before the first run, with no line', () => {
    const html = draw([made('a')])
    expect(html).toContain('No runs yet')
    expect(html).not.toContain('role="img"')
  })

  it('names the board by its heading and counts every workflow, even the ones it does not draw', () => {
    const many = Array.from({ length: BOARD_SHOWN + 2 }, (_, index) => made(`w${String(index)}`))
    const html = draw(many)
    expect(html).toContain(`Your workflows <span class="`)
    expect(html).toContain(String(BOARD_SHOWN + 2))
    expect(html).toContain('See all on Workflows')
    expect(draw([made('a')])).not.toContain('See all')
  })

  it('says why a workflow needs the person once, in Needs you: its tile has the pill and no sentence about the stop', () => {
    const html = draw([made('a', { needs_you: 'stopped', last_run: lastRun('failed', { stop: { at: '2026-11-27T00:00:00Z', what_happened: 'GitHub did not answer.' } }) })], new Map([['a', STEPS]]))
    expect(html).toContain('Needs you')
    expect(html).not.toContain('GitHub did not answer')
  })
})

describe('the line that says nothing needs the person', () => {
  const line = (text: string | null, soon: UseCaseView[]) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <NextUp title={text} next={soon.length ? { name: soon[0]?.name ?? '', when: 'Monday 9:00' } : null} />
      </MemoryRouter>,
    )

  it('says so, with the next run', () => {
    const html = line('Nothing needs you.', [made('a')])
    expect(html).toContain('Nothing needs you.')
    expect(html).toContain('Next run')
    expect(html).toContain('Workflow a')
    expect(html).toContain('Monday 9:00')
  })

  it('leaves out the sentence when the page’s heading already says it, and says nothing with no next run either', () => {
    expect(line(null, [made('a')])).not.toContain('Nothing needs')
    expect(line(null, [])).toBe('')
  })
})
