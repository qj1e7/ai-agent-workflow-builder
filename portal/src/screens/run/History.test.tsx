import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { History } from './History'
import type { LogRow } from './words'

const row = (seq: number, text: string, agent: LogRow['agent'] = null): LogRow => ({ seq, at: Date.parse('2026-11-25T02:00:00Z'), time: '10:00:00', text, agent, tone: 'plain', gate: false, keys: [], urls: undefined })
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

function draw(open: boolean, messages: readonly LogRow[] = []): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <History rows={[row(1, 'Checked GitHub: found 1.2.16'), row(2, 'Drafted 1 Jira ticket')]} messages={messages} loadedUpTo={9} open={open} onToggle={() => undefined} />
    </MemoryRouter>,
  )
}

describe('the folded history', () => {
  it('is named Run history, so a stopped page has one What happened, the troubleshooter’s', () => {
    const words = text(draw(false))
    expect(words).toContain('Run history (2 steps)')
    expect(words).not.toContain('What happened')
  })

  it('names its list Run history', () => {
    expect(draw(true)).toContain('aria-label="Run history"')
  })

  it('offers the agents’ own words only when there are some', () => {
    expect(draw(true)).not.toContain('Show agent messages')
    expect(draw(true, [row(3, 'Please run your plan.', { id: 'planner', display: 'Planner' })])).toContain('Show agent messages')
  })
})
