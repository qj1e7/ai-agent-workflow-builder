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
import { TicketLinksProvider } from '../../api/ticketLinks'
import { createDevSession } from '../../api/session'
import type { FindOut, Me, ProjectGuess, ScheduleHold, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { AddSoftwareForm } from './AddSoftware'
import { addReducer, readyToAdd, START, type AddAction, type AddState } from './addByName'
import { FindSoftware } from './FindSoftware'
import { SoftwareRoute } from './SoftwarePage'
import { SoftwareHistory } from './SoftwareHistory'
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
    expect(words).toContain('Needs attention 2')
    expect(words).toContain('Software we watch 4')
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

const GUESS: ProjectGuess = {
  repo: 'langchain-ai/langgraph',
  what: 'LangGraph, a Python library for building AI agents',
  why: 'From our list of known projects.',
  releases: 'published',
  newest: '1.2.20',
  already_listed: null,
}
const TERRAFORM: ProjectGuess = { ...GUESS, repo: 'hashicorp/terraform', what: 'Terraform itself, from HashiCorp', newest: 'v1.9.8' }
const OPENTOFU: ProjectGuess = { ...GUESS, repo: 'opentofu/opentofu', what: 'OpenTofu, an open-source fork of Terraform', newest: 'v1.8.5' }

const found = (...matches: ProjectGuess[]): FindOut => ({ status: 'found', matches })
const run = (name: string, ...actions: AddAction[]): AddState =>
  actions.reduce(addReducer, addReducer(START, { type: 'typed', field: 'name', value: name }))
const form = (state: AddState, busy = false) => renderToStaticMarkup(<AddSoftwareForm state={state} busy={busy} />)

describe('the order of the page', () => {
  const headings = (html: string) => [...html.matchAll(/<h2[^>]*>([\s\S]*?)<\/h2>/g)].map((m) => text(m[1] ?? '').replace(/ \d+$/, ''))

  it('leads with what needs attention, then the software we watch, then how it is checked', () => {
    expect(headings(render(statuses, ALICE))).toEqual(['Needs attention', 'Software we watch', 'How it’s checked'])
  })

  it('has no Needs attention section when nothing needs it', () => {
    const calm = { ...(statuses as WatchlistView), software: (statuses as WatchlistView).software.filter((row) => row.status === 'up_to_date' || row.status === 'not_checked') }
    expect(headings(render(calm, ALICE))).toEqual(['Software we watch', 'How it’s checked'])
  })

  it('puts the row that waits for a yes in Needs attention with its way to decide', () => {
    const html = render(statuses, ALICE)
    const attention = html.slice(html.indexOf('needs-attention-heading'), html.indexOf('software-we-watch-heading'))
    expect(text(attention)).toContain('Ticket waiting for a yes')
    expect(text(attention)).toContain('Review and decide')
    expect(text(attention)).toContain('Can’t check')
    expect(text(attention)).not.toContain('Up to date')
  })

  it('says how it is checked with the schedule and the one source that works', () => {
    const words = text(render(statuses, ALICE))
    expect(words).toContain('How it’s checked')
    expect(words).toContain('GitHub is the only place we can check today')
  })

  it('puts Add software inside Software we watch for an Operator, and not at all for an Approver', () => {
    const operator = render(statuses, ALICE)
    expect(operator.indexOf('Add software')).toBeGreaterThan(operator.indexOf('software-we-watch-heading'))
    expect(operator.indexOf('Add software')).toBeLessThan(operator.indexOf('how-checked-heading'))
    expect(text(render(statuses, BOB))).not.toContain('Add software')
  })
})

describe('what the team runs', () => {
  const row = (changes: Partial<WatchedSoftwareView>): WatchedSoftwareView => ({ ...(statuses as WatchlistView).software[0]!, ...changes })

  it('says Not known when nobody knows, and never shows the newest release in its place', () => {
    const unknown = row({ our_version: null, our_version_source: { kind: 'first_check', at: '2026-11-09T01:00:00Z', ticket: null }, compared_from: '8.2.0', newest_version: '8.2.1', status: 'behind' })
    const words = text(render({ ...(statuses as WatchlistView), software: [unknown] }, ALICE))
    expect(words).toContain('Ours Not known')
    expect(words).toContain('Telling you about releases newer than 8.2.0, the newest the first check read')
    expect(words).not.toContain('Ours 8.2')
  })

  it('says the first check starts the comparison before any check has read the newest', () => {
    const fresh = row({ our_version: null, our_version_source: null, compared_from: null, status: 'not_checked', newest_version: null, newest_read_at: null, checked_at: null })
    const words = text(render({ ...(statuses as WatchlistView), software: [fresh] }, ALICE))
    expect(words).toContain('Ours Not known The first check reads the newest release. Later checks tell you about newer ones')
  })
})

describe('add software by name', () => {
  it('starts with the name and one way forward, plus a way to type the address instead', () => {
    const html = form(START)
    expect(text(html)).toContain('Software name')
    expect(buttons(html)).toEqual(['Find it', 'I have the GitHub address'])
    expect(html).not.toContain('id="sw-repo"')
  })

  it('shows a plain problem under the name and marks it invalid', () => {
    const html = form(addReducer(START, { type: 'refused', errors: { name: 'Give the software a name.' } }))
    expect(html).toContain('aria-invalid="true"')
    expect(html).toContain('aria-describedby="sw-name-error"')
  })

  it('shows one match with where the guess came from, that it was checked, and a way to change it', () => {
    const html = form(run('LangGraph', { type: 'answered', answer: found(GUESS) }))
    const words = text(html)
    expect(words).toContain('Adding LangGraph')
    expect(words).toContain('langchain-ai/langgraph')
    expect(words).toContain('From our list of known projects.')
    expect(words).toContain('Checked just now. The project is on GitHub and its newest release is 1.2.20.')
    expect(buttons(html)).toEqual(['Looks right, add it', 'Change', 'Start again'])
    expect(html).not.toContain('id="sw-repo"')
  })

  it('lets the person choose between several matches, and keeps None of these', () => {
    const state = run('Terraform', { type: 'answered', answer: found(TERRAFORM, OPENTOFU) })
    const html = form(state)
    expect(text(html)).toContain('Which one do you mean?')
    expect(html.match(/type="radio"/g)).toHaveLength(2)
    expect(html).not.toContain('checked=""')
    expect(text(html)).toContain('Terraform itself, from HashiCorp')
    expect(text(html)).toContain('OpenTofu, an open-source fork of Terraform')
    expect(buttons(html)).toEqual(['Add Terraform', 'None of these', 'Start again'])
    expect(form(addReducer(state, { type: 'picked', index: 1 }))).toContain('checked=""')
  })

  it('shows the repository field when the person changes the guess, starting from the guess', () => {
    const html = form(run('LangGraph', { type: 'answered', answer: found(GUESS) }, { type: 'change' }))
    expect(html).toContain('id="sw-repo"')
    expect(html).toContain('value="langchain-ai/langgraph"')
    expect(text(html)).toContain('You’re choosing the project yourself.')
  })

  it('says plainly when the list has no such name, and falls back to the repository field', () => {
    const answer: FindOut = { status: 'not_known', message: 'I don’t know a GitHub project called Zorblax. Type the GitHub address instead, as owner/name.' }
    const html = form(run('Zorblax', { type: 'answered', answer }))
    expect(text(html)).toContain('I couldn’t find “Zorblax”')
    expect(text(html)).toContain('I don’t know a GitHub project called Zorblax.')
    expect(html).toContain('id="sw-repo"')
    expect(buttons(html)).toEqual(['Add Zorblax', 'Start again'])
  })

  it('offers no project when GitHub could not be asked, and says what went wrong as an alert', () => {
    const answer: FindOut = { status: 'not_checked', message: 'I couldn’t reach GitHub, so I can’t check Redis yet. Try again later.' }
    const html = form(run('Redis', { type: 'answered', answer }))
    expect(html).toContain('role="alert"')
    expect(text(html)).toContain('I couldn’t reach GitHub, so I can’t check Redis yet.')
    expect(html).not.toContain('type="radio"')
    expect(html).toContain('id="sw-repo"')
  })

  it('warns when a match has no release the check can compare', () => {
    const none: ProjectGuess = { ...GUESS, releases: 'none', newest: null }
    expect(text(form(run('LangGraph', { type: 'answered', answer: found(none) })))).toContain('it has no release this check can compare yet')
  })

  it('says a match is already on the list, and offers no way to add it twice', () => {
    const listed: ProjectGuess = { ...GUESS, already_listed: 'LangGraph' }
    const state = run('LangGraph again', { type: 'answered', answer: found(listed) })
    expect(text(form(state))).toContain('langchain-ai/langgraph is already on the list as LangGraph.')
    expect(readyToAdd(state, [], [])).toEqual({ ok: false, errors: { form: 'langchain-ai/langgraph is already on the list as LangGraph.' } })
  })

  it('shows the repository field straight away when the person types the address instead', () => {
    const html = form(run('', { type: 'typeAddress' }))
    expect(html).toContain('id="sw-repo"')
    expect(text(html)).toContain('You’re choosing the project yourself.')
  })

  it('has a version field that says what an empty one means, and does not fill it from the newest release', () => {
    const state = run('LangGraph', { type: 'answered', answer: found(GUESS) })
    const html = form(state)
    expect(html).toContain('id="sw-version"')
    expect(html).toContain('value=""')
    expect(text(html)).toContain('It shows as Not known')
  })

  it('shows the Find button as busy while the finder is asked, and stays a button', () => {
    expect(form(START, true)).toContain('aria-busy="true"')
  })
})

describe('what the add form sends', () => {
  const single = run('  LangGraph ', { type: 'answered', answer: found(GUESS) })

  it('sends the trimmed name and the confirmed repository, with no version when none was typed', () => {
    expect(readyToAdd(single, [], [])).toEqual({ ok: true, body: { name: 'LangGraph', repo: 'langchain-ai/langgraph' } })
  })

  it('sends the version the person typed, and only that', () => {
    const typed = addReducer(single, { type: 'typed', field: 'version', value: '1.2.14' })
    expect(readyToAdd(typed, [], [])).toEqual({ ok: true, body: { name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: '1.2.14' } })
  })

  it('asks the person to choose before adding when there are several matches', () => {
    const state = run('Terraform', { type: 'answered', answer: found(TERRAFORM, OPENTOFU) })
    expect(readyToAdd(state, [], [])).toEqual({ ok: false, errors: { form: 'Choose one project first, or press None of these.' } })
    const chosen = addReducer(state, { type: 'picked', index: 1 })
    expect(readyToAdd(chosen, [], [])).toEqual({ ok: true, body: { name: 'Terraform', repo: 'opentofu/opentofu' } })
  })

  it('sends the address the person typed when nothing matched, checked like any typed address', () => {
    const unknown = run('Zorblax', { type: 'answered', answer: { status: 'not_known', message: 'No.' } })
    expect(readyToAdd(unknown, [], []).ok).toBe(false)
    const typed = addReducer(unknown, { type: 'typed', field: 'repo', value: 'https://github.com/acme/zorblax' })
    expect(readyToAdd(typed, [], [])).toEqual({ ok: true, body: { name: 'Zorblax', repo: 'acme/zorblax' } })
  })

  it('sends the address the person changed to, not the guess', () => {
    const changed = addReducer(addReducer(single, { type: 'change' }), { type: 'typed', field: 'repo', value: 'acme/other' })
    expect(readyToAdd(changed, [], [])).toEqual({ ok: true, body: { name: 'LangGraph', repo: 'acme/other' } })
  })

  it('refuses a bad version and names the field', () => {
    const bad = addReducer(single, { type: 'typed', field: 'version', value: '1.2' })
    expect(readyToAdd(bad, [], [])).toEqual({ ok: false, errors: { version: 'Type the version as three numbers, such as 1.2.14.' } })
  })

  it('answers a name of spaces with a plain ask for a name', () => {
    const blank = run('   ')
    expect(readyToAdd(blank, [], [])).toMatchObject({ ok: false, errors: { name: 'Give the software a name.' } })
  })

  it('goes back to the start when the person starts again', () => {
    expect(addReducer(single, { type: 'reset' })).toEqual(START)
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

describe('ticket keys on the Software watchlist', () => {
  // The project is a setting, so none of these keys is MOCK.
  const rows = (statuses as WatchlistView).software
  const open = rows.find((row) => row.status === 'ticket_open')!
  const view = {
    ...statuses,
    software: rows.map((row) =>
      row.id === open.id
        ? { ...row, open_ticket: 'OPS-143', our_version_source: { kind: 'ticket_done', at: '2026-11-13T14:30:00+08:00', ticket: 'OPS-140' } }
        : row,
    ),
  }
  const link = (key: string) => new RegExp(`<a\\b[^>]*href="/jira/${key}"[^>]*>${key}`)

  it('links the open ticket and the ticket our version came from, whatever the project', () => {
    const html = render(view, ALICE)
    expect(html).toMatch(link('OPS-143'))
    expect(html).toMatch(link('OPS-140'))
  })

  it('links the keys in the history lines', () => {
    const row = view.software.find((item) => item.id === open.id)!
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <SoftwareHistory row={row as WatchedSoftwareView} nameOf={(id) => id} id="h" />
      </MemoryRouter>,
    )
    expect(html).toMatch(link('OPS-143'))
    expect(html).toMatch(link('OPS-140'))
    expect(text(html)).toContain('OPS-143 is open in Jira for the upgrade.')
  })

  it('does not link key-like words that are not tickets the row holds', () => {
    const html = render({ ...view, software: view.software.map((row) => ({ ...row, problem: 'UTF-8 and CVE-2024-1234' })) }, ALICE)
    expect(html).not.toContain('href="/jira/UTF-8"')
    expect(html).not.toContain('href="/jira/CVE-2024-1234"')
  })

  it('links to the real Jira in a new tab, safely, when an address is configured', () => {
    const html = render(view, ALICE, [], (
      <TicketLinksProvider config={{ jiraBrowseUrl: 'https://jira.example.test/browse/{key}' }}>
        <SoftwareRoute />
      </TicketLinksProvider>
    ))
    expect(html).toMatch(/<a\b[^>]*href="https:\/\/jira.example.test\/browse\/OPS-143"[^>]*target="_blank"[^>]*rel="noopener noreferrer"[^>]*>OPS-143/)
    expect(html).not.toContain('href="/jira/OPS-143"')
  })
})
