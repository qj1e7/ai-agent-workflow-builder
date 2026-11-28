import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { UseCaseView } from '../../api/types'
import { FlowDiagram } from './FlowDiagram'
import { flowOf } from './flow'

const UC = useCase as unknown as UseCaseView
const NOW = new Date('2026-11-04T15:00:00+08:00')
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const draw = (events: readonly unknown[] | null) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <FlowDiagram flow={flowOf(UC, events ? { runId: (events[0] as { run_id: string }).run_id, events, startedAt: '2026-11-04T00:00:00Z' } : null, NOW)} />
    </MemoryRouter>,
  )

describe('the flow diagram with no run', () => {
  const html = draw(null)

  it('has a Steps heading and a list of boxes, and no key, time or state word', () => {
    expect(html).toMatch(/<h2[^>]*>Steps<\/h2>/)
    expect(html).toContain('aria-label="Steps"')
    expect(html.match(/<li /g)).toHaveLength(4)
    expect(html).not.toContain('data-state=')
    expect(html).not.toMatch(/Not reached|with today/)
    expect(html).not.toContain('visually-hidden')
  })

  it('shows an Orb on the agent step and the icon on the others, each with its tag', () => {
    expect(html.match(/data-face="orb"/g)).toHaveLength(1)
    expect(text(html)).toContain('Reads only')
    expect(text(html)).toContain('Writes after approval')
  })
})

describe('the flow diagram with a run', () => {
  it("adds the run's time to the heading and a key of the states shown, once each", () => {
    const html = draw(success)
    expect(text(html)).toContain('Steps with today’s 8:00 run')
    expect(html.match(/data-key="done"/g)).toHaveLength(1)
    expect(html).not.toContain('data-key="err"')
  })

  it("says each box's state to a screen reader in the one word map", () => {
    const html = draw(success)
    expect(html.match(/class="visually-hidden">Done: </g)).toHaveLength(4)
  })

  it('puts a note under the stopped step, and marks the key', () => {
    const html = draw(failure)
    expect(html).toContain('data-key="err"')
    expect(html).toMatch(/data-note="err"/)
    expect(html).toContain('Stopped here')
  })

  it('puts a note under the gate that waits', () => {
    const html = draw(success.filter((event) => event.seq <= 15))
    expect(html).toMatch(/data-note="wait"[^>]*>[\s\S]*Waiting for approval/)
  })
})
