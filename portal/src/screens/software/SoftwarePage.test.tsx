import failedRun from '@contracts/fixtures/views/failure.final.json'
import empty from '@contracts/fixtures/watchlist/empty.json'
import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, WatchlistView } from '../../api/types'
import { AddSoftwareFields, EMPTY_VALUES } from './AddSoftware'
import { SoftwareRoute } from './SoftwarePage'
import { ScheduleNote } from './Schedule'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

function render(view: unknown, me: Me, runs: readonly { run_id: string }[] = []): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['watchlist', session.cacheScope()], view)
  for (const run of runs) queryClient.setQueryData(['run', session.cacheScope(), run.run_id], run)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <SoftwareRoute />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

describe('the Software watchlist page', () => {
  it('lists each software with our version, the newest and its status', () => {
    const html = render(statuses, ALICE)
    const words = text(html)
    for (const row of (statuses as WatchlistView).software) expect(words).toContain(row.name)
    expect(words).toContain('Needs a person 4')
    expect(words).toContain('Not checked yet 1')
    expect(words).toContain('Up to date 1')
    expect(words).toContain('1.2.14')
    expect(words).toContain('1.2.16')
    expect(words).toContain('Ticket waiting for a yes')
  })

  it('says a check could not reach the source and will try at the next check', () => {
    expect(text(render(statuses, ALICE))).toContain('Can’t check right now. It will try again at the next check.')
  })

  it('says the last check stopped, why, and when, and links to its run', () => {
    const stopped = { ...statuses, last_check: { run_id: failedRun.run_id, state: 'failed', started_at: failedRun.started_at } }
    const html = render(stopped, BOB, [failedRun])
    expect(text(html)).toContain('The last check stopped: an agent could not finish its work. Started Wed 4 Nov, 10:14, Singapore time.')
    expect(html).toContain(`href="/runs/${failedRun.run_id}"`)
    expect(text(render(stopped, BOB))).toContain('The last check stopped. Started Wed 4 Nov, 10:14')
  })

  it('says nothing about the last check while it has not stopped', () => {
    expect(text(render(statuses, ALICE))).not.toContain('The last check stopped')
  })

  it('shows the schedule in Singapore time and names its owner', () => {
    const words = text(render(statuses, ALICE))
    expect(words).toContain('Checked every Monday at 9:00, set by Alice.')
    expect(words).toContain('Next check Mon 23 Nov, 9:00, Singapore time.')
    expect(words).toContain('Alice can’t approve them')
  })

  it('gives an Operator Check now, Remove, Change schedule and the add form', () => {
    const html = render(statuses, ALICE)
    expect(buttons(html)).toContain('Check now')
    expect(buttons(html)).toContain('Change schedule')
    expect(buttons(html).some((label) => label.startsWith('Remove'))).toBe(true)
    expect(html).toContain('Add software')
  })

  it('gives an Approver the list and no way to add, remove, schedule or check', () => {
    const html = render(statuses, BOB)
    const labels = buttons(html)
    expect(text(html)).toContain('FastAPI')
    expect(labels.some((label) => /^(Check now|Remove|Change schedule|Set a schedule|Turn off schedule|Add)/.test(label))).toBe(false)
    expect(html).not.toContain('Add software')
    expect(labels.some((label) => label.startsWith('History'))).toBe(true)
  })

  it('has a search box that announces its result count', () => {
    const html = render(statuses, ALICE)
    expect(html).toContain('type="search"')
    expect(html).toMatch(/role="status"/)
  })

  it('invites an Operator to add the first software when the list is empty', () => {
    const html = render({ ...empty, schedule: null }, ALICE)
    expect(text(html)).toContain('No software yet')
    expect(text(html)).toContain('Add the tools your team runs')
    expect(buttons(html)).not.toContain('Check now')
  })

  it('tells an Approver an Operator can add software when the list is empty', () => {
    const words = text(render(null, BOB))
    expect(words).toContain('No software yet')
    expect(words).toContain('An Operator can add')
  })
})

describe('the add form', () => {
  const fields = (errors: Parameters<typeof AddSoftwareFields>[0]['errors']) =>
    renderToStaticMarkup(<AddSoftwareFields values={EMPTY_VALUES} errors={errors} busy={false} />)

  it('says only GitHub works today', () => {
    expect(text(fields({}))).toContain('GitHub is the only place we can check today')
  })

  it('shows each error beside its field and marks the field invalid', () => {
    const html = fields({ repo: 'That doesn’t look like a GitHub project. Paste its GitHub link, or type owner/name.' })
    expect(html).toContain('aria-invalid="true"')
    expect(html).toContain('id="sw-repo-error"')
    expect(html).toContain('aria-describedby="sw-repo-error"')
    expect(text(html)).toContain('That doesn’t look like a GitHub project')
  })

  it('shows help, not an error, when the fields are fine', () => {
    const html = fields({})
    expect(html).not.toContain('aria-invalid')
    expect(html).toContain('id="sw-version-help"')
  })
})

describe('the schedule note', () => {
  it('says no schedule is set', () => {
    expect(text(renderToStaticMarkup(<ScheduleNote schedule={null} />))).toContain('No schedule yet')
  })
})
