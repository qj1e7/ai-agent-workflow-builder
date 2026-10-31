import failedRun from '@contracts/fixtures/views/failure.final.json'
import empty from '@contracts/fixtures/watchlist/empty.json'
import paused from '@contracts/fixtures/watchlist/paused.json'
import held from '@contracts/fixtures/watchlist/schedule.held.json'
import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, ScheduleHold, WatchlistView } from '../../api/types'
import { AddSoftwareFields, EMPTY_VALUES } from './AddSoftware'
import { FindSoftware } from './FindSoftware'
import { SoftwareRoute } from './SoftwarePage'
import { ScheduleEditor, ScheduleNote } from './Schedule'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

function render(view: unknown, me: Me, runs: readonly { run_id: string }[] = [], page: ReactNode = <SoftwareRoute />): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['watchlist', session.cacheScope()], view)
  for (const run of runs) queryClient.setQueryData(['run', session.cacheScope(), run.run_id], run)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{page}</MemoryRouter>
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

  it('says on the row why a check could not read the source, and that it will try at the next check', () => {
    expect(text(render(statuses, ALICE))).toContain('Can’t check GitHub answered 404 Not Found. It will try again at the next check.')
  })

  it('keeps the newest version an earlier check read on a row that can’t be checked, and says when it was read', () => {
    expect(text(render(statuses, ALICE))).toContain('Newest 0.115.2 Last read Mon 9 Nov, 9:00')
  })

  it('promises no next check when no schedule is set', () => {
    const words = text(render({ ...statuses, schedule: null }, ALICE))
    expect(words).not.toContain('next check')
    expect(words).toContain('GitHub answered 404 Not Found. It is checked again when an Operator presses Check now.')
    expect(words).toContain('No schedule. Press Check now to check by hand.')
    expect(text(render({ ...empty, schedule: null }, ALICE))).toContain('Add the tools your team runs, then press Check now to check them.')
  })

  it('says the last check stopped, why, and when, and links to its run', () => {
    const stopped = { ...statuses, last_check: { run_id: failedRun.run_id, state: 'failed', started_at: failedRun.started_at } }
    const html = render(stopped, BOB, [failedRun])
    expect(text(html)).toContain('The last check stopped: an agent could not finish its work. Started Wed 4 Nov, 10:14, Singapore time.')
    expect(html).toContain(`href="/runs/${failedRun.run_id}"`)
    expect(text(render(stopped, BOB))).toContain('The last check stopped. Started Wed 4 Nov, 10:14')
  })

  it('says the watchlist is paused, with no next check time, while it is paused', () => {
    expect((paused as WatchlistView).schedule?.next_at).toBeNull()
    const words = text(render(paused, ALICE))
    expect(words).toContain('Paused. No check runs until an Operator resumes it.')
    expect(words).toContain('Checked every Monday at 9:00, set by Alice.')
    expect(words).not.toContain('Next check')
    expect(words).not.toContain('It will try again at the next check')
    expect(words).toContain('GitHub answered 404 Not Found. It is checked again once the watchlist is resumed.')
    expect(words).toContain('Change schedule')
    expect(buttons(render(paused, ALICE))).not.toContain('Check now')
    expect(buttons(render(statuses, ALICE))).toContain('Check now')
  })

  it('gives an Operator Resume while the watchlist is paused, and never a Pause', () => {
    expect(buttons(render(paused, ALICE))).toContain('Resume')
    expect(buttons(render({ ...paused, schedule: null }, ALICE))).toContain('Resume')
    expect(buttons(render(statuses, ALICE))).not.toContain('Resume')
    for (const view of [paused, statuses]) expect(buttons(render(view, ALICE))).not.toContain('Pause')
  })

  it('gives an Approver no Resume', () => {
    expect(buttons(render(paused, BOB))).not.toContain('Resume')
  })

  it('puts Resume first among the schedule controls, so the schedule button takes its place once it resumes', () => {
    const places = (html: string) => [...html.matchAll(/data-place="([^"]+)"/g)].map((match) => match[1])
    expect(places(render(paused, ALICE))).toEqual(['resume', 'schedule', 'schedule-off'])
    expect(places(render(statuses, ALICE))).toEqual(['schedule', 'schedule-off'])
    expect(places(render({ ...paused, schedule: null }, ALICE))).toEqual(['resume', 'schedule'])
  })

  it('does not point to the hidden Check now while paused with no schedule', () => {
    const words = text(render({ ...paused, schedule: null }, ALICE))
    expect(words).toContain('No schedule. Paused. No check runs until an Operator resumes it.')
    expect(words).not.toContain('Press Check now')
    expect(buttons(render({ ...paused, schedule: null }, ALICE))).not.toContain('Check now')
  })

  it('reads as before while the watchlist is on, with its next check time and no paused words', () => {
    const words = text(render(statuses, ALICE))
    expect((statuses as WatchlistView).state).toBe('on')
    expect(words).toContain('Next check Mon 23 Nov, 9:00, Singapore time.')
    expect(words).not.toContain('Paused')
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

  it('for a London schedule, names London next to the schedule and the next check', () => {
    const london = { ...statuses, schedule: { ...statuses.schedule, time_zone: 'Europe/London', next_at: '2026-11-23T09:00:00Z' } }
    const words = text(render(london, ALICE))
    expect(words).toContain('Checked every Monday at 9:00 London time, set by Alice.')
    expect(words).toContain('Next check Mon 23 Nov, 9:00, London time.')
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

  it('keeps an empty status line on the page, so a screen reader hears each change to the list', () => {
    expect(render(statuses, ALICE)).toContain('<p role="status"></p>')
  })

  it('lets the notice take focus, for a removal the platform says was done already', () => {
    expect(render(statuses, ALICE)).toMatch(/<div[^>]*id="change-notice"[^>]*tabindex="-1"[^>]*><p role="status"><\/p><\/div>/)
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

describe('the search box', () => {
  const find = (query: string, shown: number) => renderToStaticMarkup(<FindSoftware query={query} shown={shown} onChange={() => undefined} />)
  const heard = (said: string) => `<p class="visually-hidden" role="status">${said}</p>`

  it('tells a screen reader the count of matching rows, and nothing before a search', () => {
    expect(find('', 14)).toContain(heard(''))
    expect(find('lang', 1)).toContain(heard('1 match'))
    expect(find('Tool 0', 9)).toContain(heard('9 matches'))
    expect(find('zzz', 0)).toContain(heard('No matches'))
  })

  it('is a search field with its own label', () => {
    const html = find('', 14)
    expect(html).toContain('<label for="find-software">Find software</label>')
    expect(html).toContain('id="find-software" type="search"')
  })

  it('is on the page with the list', () => {
    expect(render(statuses, ALICE)).toContain(find('', 6))
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

describe('a schedule held because its owner can no longer run it', () => {
  const PAUSED_WORDS = 'Paused. No check runs until an Operator resumes it.'
  const OWNER_WORDS = 'Scheduled checks count as'
  const heldFor = (hold: ScheduleHold, ownerName = 'Alice') => {
    const view = held as WatchlistView
    if (view.schedule === null) throw new Error('the held fixture has a schedule')
    return { ...view, schedule: { ...view.schedule, held: hold, owner_name: ownerName } }
  }

  it('says the owner is no longer on the People list, and promises no next check anywhere on the page', () => {
    const words = text(render(held, ALICE))
    expect(words).toContain('Not running: Alice is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(words).not.toContain(PAUSED_WORDS)
    expect(words).not.toContain('Next check')
    expect(words).not.toContain('It will try again at the next check')
    expect(words).not.toContain(OWNER_WORDS)
    expect(words).toContain('GitHub answered 404 Not Found. It is checked again when an Operator presses Check now.')
    expect(buttons(render(held, ALICE))).toEqual(expect.arrayContaining(['Check now', 'Change schedule']))
  })

  it('says the owner can no longer run workflows when they are no longer an Operator', () => {
    const words = text(render(heldFor('owner_not_an_operator'), BOB))
    expect(words).toContain('Not running: Alice can no longer run workflows. An Operator can take it over by saving the schedule.')
    expect(words).not.toContain(PAUSED_WORDS)
    expect(words).not.toContain(OWNER_WORDS)
  })

  it('says its owner when the view gives no name', () => {
    expect(text(render(heldFor('owner_removed', ''), BOB))).toContain('Not running: its owner is no longer on the People list. An Operator can take it over by saving the schedule.')
    expect(text(render(heldFor('owner_not_an_operator', ' '), BOB))).toContain('Not running: its owner can no longer run workflows.')
  })

  it('still says whose work the checks are while the schedule is not held, paused or not', () => {
    expect(text(render(statuses, BOB))).toContain('Scheduled checks count as Alice’s work, so Alice can’t approve them.')
    expect(text(render(paused, BOB))).toContain('Scheduled checks count as Alice’s work, so Alice can’t approve them.')
  })

  it('keeps the paused words while the watchlist is paused as well', () => {
    for (const hold of ['owner_removed', 'owner_not_an_operator'] as const) {
      const words = text(render({ ...heldFor(hold), state: 'paused' }, ALICE))
      expect(words).toContain(PAUSED_WORDS)
      expect(words).not.toContain('Not running')
      expect(words).not.toContain(OWNER_WORDS)
    }
  })
})

describe('the schedule editor', () => {
  it('warns before saving that the person saving becomes the owner and cannot approve its checks', () => {
    const html = render(statuses, ALICE, [], <ScheduleEditor schedule={(statuses as WatchlistView).schedule} onDone={() => undefined} />)
    expect(text(html)).toContain('Saving makes you the owner of this schedule. Its checks then count as your work, so you won’t be able to approve them.')
    expect(html).toMatch(/<button[^>]*type="submit"[^>]*aria-describedby="sched-owner-note"/)
  })
})

describe('the schedule note', () => {
  it('says no schedule is set and how a check starts then', () => {
    expect(text(renderToStaticMarkup(<ScheduleNote schedule={null} operator paused={false} />))).toBe('No schedule. Press Check now to check by hand.')
    expect(text(renderToStaticMarkup(<ScheduleNote schedule={null} operator={false} paused={false} />))).toBe('No schedule. An Operator can press Check now to check by hand.')
  })
})
