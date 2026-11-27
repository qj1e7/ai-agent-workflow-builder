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
  it('list each run as it went, newest first, with its stage words and its pill, each opening its own run page', () => {
    const html = render([failed as RunView, done as RunView])
    expect(links(html)).toEqual(['/runs/run_01JB9', '/runs/run_01JB8'])
    const said = text(html)
    expect(said, 'the run says what the troubleshooter says of it, and its GitHub failure is GitHub not answering').toContain("Today, 10:14 GitHub didn't answer Stopped")
    expect(said).toContain('Tue 3 Nov, 10:14 1 ticket created, approved by Bob Done')
  })

  it('says why a run stopped in the troubleshooter’s sentence from the platform, never a guess from the reason code', () => {
    const noStart = {
      ...(failed as RunView),
      stage: 'pending',
      reason: 'DispatchFailed',
      retryable: false,
      message: 'n8n did not take the start: the workflow has no Start from the Portal block to start it',
      what_happened: "The workflow has no Start from the Portal block, so the Portal couldn't start it.",
    } as RunView
    const said = text(render([noStart]))
    expect(said).toContain("Today, 10:14 The workflow has no Start from the Portal block, so the Portal couldn't start it Stopped")
    expect(said).not.toContain('could not be reached')
  })

  it('dates a stopped run by when it last stopped, the time the Workflows row and Needs you give', () => {
    const retried = { ...(failed as RunView), started_at: '2026-11-02T06:53:05Z', updated_at: '2026-11-04T04:06:57Z' }
    expect(text(render([retried]))).toContain('Today, 12:06 ')
    expect(text(render([retried]))).not.toContain('Mon 2 Nov')
  })

  it('has one heading, Recent runs', () => {
    expect(render([done as RunView])).toContain('>Recent runs</h2>')
  })

  it('says a run in progress is running, and one that wrote nothing is Nothing new', () => {
    expect(text(render([scheduled as RunView]))).toContain('Running')
    expect(text(render([{ ...(done as RunView), outcome: 'nothing_to_write', written: [] } as RunView]))).toContain('Nothing new to write Nothing new')
  })

  it('show the newest ones first and offer the older ones on request', () => {
    const many = Array.from({ length: RECENT_LIMIT + 3 }, (_, i) => ({ ...(done as RunView), run_id: `run_${String(i).padStart(2, '0')}` }))
    const html = render(many)
    expect(links(html)).toHaveLength(RECENT_LIMIT)
    expect(text(html)).toContain('Show 3 older runs')
  })

  it('say there are no runs yet, and when the first one is', () => {
    expect(text(render([]))).toContain('No runs yet First run Mon 9 Nov, 9:00.')
    expect(text(render([], null))).toContain('No runs yet')
    expect(text(render([], null))).not.toContain('First run')
  })
})
