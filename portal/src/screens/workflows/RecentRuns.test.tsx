import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import scheduled from '../../../../contracts/fixtures/views/scheduled.pending.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import type { RunView } from '../../api/types'
import { RECENT_LIMIT, RecentRuns } from './RecentRuns'

const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob' }
const nameOf = (id: string) => NAMES[id] ?? id
const NOW = new Date('2026-11-04T15:00:00+08:00')

function render(runs: RunView[], firstRun: string | null = 'Mon 9 Nov, 9:00'): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <RecentRuns runs={runs} now={NOW} nameOf={nameOf} firstRun={firstRun} />
    </MemoryRouter>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const links = (html: string) => [...html.matchAll(/<a[^>]*href="([^"]+)"/g)].map((m) => m[1])

describe('the recent runs of a workflow', () => {
  it('list each run as it went, newest first, each opening its own run page', () => {
    const html = render([failed as RunView, done as RunView])
    expect(links(html)).toEqual(['/runs/run_01JB9', '/runs/run_01JB8'])
    const said = text(html)
    expect(said).toContain('Today, 10:14 Stopped. An agent could not finish its work. Started by Alice')
    expect(said).toContain('Tue 3 Nov, 10:14 Done. 1 ticket created, approved by Bob. Started by Alice')
  })

  it('say when a schedule started a run', () => {
    expect(text(render([scheduled as RunView]))).toContain("Started by Alice's schedule")
  })

  it('show the newest ones first and offer the older ones on request', () => {
    const many = Array.from({ length: RECENT_LIMIT + 3 }, (_, i) => ({ ...(done as RunView), run_id: `run_${String(i).padStart(2, '0')}` }))
    const html = render(many)
    expect(links(html)).toHaveLength(RECENT_LIMIT)
    expect(text(html)).toContain('Show 3 older runs')
  })

  it('say there are no runs yet, and when the first one is', () => {
    expect(text(render([]))).toContain('No runs yet. The first one is Mon 9 Nov, 9:00.')
    expect(text(render([], null))).toContain('No runs yet.')
    expect(text(render([], null))).not.toContain('The first one')
  })
})
