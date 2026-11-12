import capabilitiesFixture from '@contracts/fixtures/planner/capabilities.json'
import failedRun from '@contracts/fixtures/views/failure.final.json'
import rejectedRun from '@contracts/fixtures/views/rejected.final.json'
import empty from '@contracts/fixtures/watchlist/empty.json'
import paused from '@contracts/fixtures/watchlist/paused.json'
import moved from '@contracts/fixtures/watchlist/moved.json'
import held from '@contracts/fixtures/watchlist/schedule.held.json'
import statuses from '@contracts/fixtures/watchlist/statuses.json'
import peopleList from '@contracts/fixtures/people/list.json'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { TicketLinksProvider } from '../../api/ticketLinks'
import { createDevSession } from '../../api/session'
import type { FindOut, Me, PersonOut, ProjectGuess, ScheduleHold, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { AppRoutes } from '../../shell/routes'
import { AddSoftwareForm } from './AddSoftware'
import { addReducer, readyToAdd, START, type AddAction, type AddState } from './addByName'
import { FindSoftware } from './FindSoftware'
import { MovedNote } from './NewAddress'
import { SoftwareRoute } from './SoftwarePage'
import { SoftwareHistory } from './SoftwareHistory'
import { ScheduleEditor, ScheduleNote } from './Schedule'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob', 'carol'].includes(person.id))

function render(view: unknown, me: Me, runs: readonly { run_id: string }[] = [], page: ReactNode = <SoftwareRoute />, capabilities: unknown = capabilitiesFixture): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', session.cacheScope()], me)
  queryClient.setQueryData(['watchlist', session.cacheScope()], view)
  for (const run of runs) queryClient.setQueryData(['run', session.cacheScope(), run.run_id], run)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB])
  queryClient.setQueryData(['people', session.cacheScope()], TEAM)
  if (capabilities !== null) queryClient.setQueryData(['capabilities', session.cacheScope()], capabilities)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={['/software']}>{page}</MemoryRouter>
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
    expect(words).toContain('Needs attention 1')
    expect(words).toContain('Software we watch 6')
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

  it('is read only for an Approver: one note under the heading names the Operators, and nothing is dead', () => {
    const page = (me: Me) => render(statuses, me, [], <AppRoutes context={{ name: me.display, now: new Date(), operator: me.roles.includes('operator') }} />)
    const head = text(page(BOB))
    expect(head.match(/Only Operators change/g)).toHaveLength(1)
    expect(head).toContain('Software watchlist')
    expect(head).toContain('Only Operators change the watchlist. Ask Alice or Carol.')
    expect(text(page(ALICE))).not.toContain('Only Operators change')
    for (const view of [statuses, paused, moved, held, null]) expect(render(view, BOB)).not.toMatch(/disabled=""|aria-disabled="true"/)
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

  it('puts one decision for the whole check in Needs attention, and no row', () => {
    const html = render(statuses, ALICE)
    const attention = html.slice(html.indexOf('needs-attention-heading'), html.indexOf('software-we-watch-heading'))
    expect(text(attention)).toContain('The latest check wants to raise 1 upgrade ticket.')
    expect(text(attention)).toContain('Nothing is written until an Approver says yes.')
    expect(text(attention)).toContain('Review and decide')
    expect(attention).not.toContain('<li')
    expect(text(attention)).not.toContain('Can’t check')
    expect(attention.match(/Review and decide/g)).toHaveLength(1)
  })

  it('keeps every row in Software we watch, with the real count, the waiting row and the one that can’t be checked included', () => {
    const view = statuses as WatchlistView
    const html = render(statuses, ALICE)
    const watching = html.slice(html.indexOf('software-we-watch-heading'), html.indexOf('how-checked-heading'))
    expect(text(watching.slice(0, 120))).toContain(`Software we watch ${view.software.length}`)
    expect(watching.match(/<li id="software-/g)).toHaveLength(view.software.length)
    expect(text(watching)).toContain('Ticket waiting for a yes')
    expect(text(watching)).toContain('Can’t check')
  })

  it('gives the primary action only to the decision when one waits, not to Check now', () => {
    const html = render(statuses, ALICE)
    const checkNow = /<button[^>]*>\s*Check now/.exec(html)?.[0] ?? ''
    expect(checkNow).not.toBe('')
    expect(html.match(/<button[^>]*class="[^"]*primary[^"]*"[^>]*>\s*Find it/)).toBeNull()
    expect(/<button[^>]*primary[^>]*>\s*Check now/.test(html)).toBe(false)
  })

  it('says how it is checked with the schedule and the one source that works', () => {
    const words = text(render(statuses, ALICE))
    expect(words).toContain('How it’s checked')
    expect(words).toContain('GitHub is the only place we can check today. We can’t check registries or security advisories yet.')
  })

  it('says GitHub is not working when the registry says so, and says nothing about sources without the registry', () => {
    const down = capabilitiesFixture.capabilities.map((c) => (c.id === 'github.releases' ? { ...c, state: 'down' as const } : c))
    expect(text(render(statuses, ALICE, [], <SoftwareRoute />, { capabilities: down, examples: [] }))).toContain('GitHub is the only place we check, and it is not working right now.')
    expect(text(render(statuses, ALICE, [], <SoftwareRoute />, null))).not.toContain('only place')
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
  it('starts with the name and one way forward', () => {
    const html = form(START)
    expect(text(html)).toContain('Software name')
    expect(buttons(html)).toEqual(['Find it'])
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

  it('says a project with no releases can’t be watched, and offers only Change and Start again', () => {
    const none: ProjectGuess = { ...GUESS, repo: 'python/cpython', releases: 'none', newest: null }
    const state = run('Python', { type: 'answered', answer: found(none) })
    const html = form(state)
    expect(text(html)).toContain('python/cpython doesn’t publish releases on GitHub, which is the only place this check reads. It can’t be watched here.')
    expect(buttons(html)).toEqual(['Change', 'Start again'])
    expect(html).not.toContain('id="sw-version"')
    expect(readyToAdd(state, [], [])).toEqual({ ok: false, errors: { form: 'python/cpython doesn’t publish releases on GitHub, which is the only place this check reads. It can’t be watched here.' } })
  })

  it('leaves a match with no releases out of the choice, and says why beside it', () => {
    const none: ProjectGuess = { ...OPENTOFU, releases: 'none', newest: null }
    const state = run('Terraform', { type: 'answered', answer: found(TERRAFORM, none) })
    const html = form(state)
    expect(html.match(/type="radio"/g)).toHaveLength(2)
    expect(html.match(/disabled=""/g)).toHaveLength(1)
    expect(text(html)).toContain('opentofu/opentofu doesn’t publish releases on GitHub')
    expect(buttons(html)).toEqual(['Add Terraform', 'None of these', 'Start again'])
  })

  it('offers no add when every match is unavailable', () => {
    const none = (match: ProjectGuess): ProjectGuess => ({ ...match, releases: 'none', newest: null })
    const html = form(run('Terraform', { type: 'answered', answer: found(none(TERRAFORM), none(OPENTOFU)) }))
    expect(buttons(html)).toEqual(['None of these', 'Start again'])
    expect(html).not.toContain('id="sw-version"')
  })

  it('says a match is already on the list, links to its row, and keeps no way to add it', () => {
    const listed: ProjectGuess = { ...GUESS, already_listed: 'LangGraph' }
    const state = run('LangGraph again', { type: 'answered', answer: found(listed) })
    const html = renderToStaticMarkup(<AddSoftwareForm state={state} busy={false} rowIdOf={() => 'sw_1'} onShowRow={() => undefined} />)
    expect(text(html)).toContain('langchain-ai/langgraph is already on the list as LangGraph.')
    expect(html).toContain('href="#software-sw_1"')
    expect(text(html)).toContain('Show it on the list')
    expect(buttons(html)).toEqual(['Change', 'Start again'])
    expect(readyToAdd(state, [], [])).toEqual({ ok: false, errors: { form: 'langchain-ai/langgraph is already on the list as LangGraph.' } })
  })

  it('does not offer a listed match in a choice', () => {
    const listed: ProjectGuess = { ...TERRAFORM, already_listed: 'Terraform' }
    const html = form(run('Terraform', { type: 'answered', answer: found(listed, OPENTOFU) }))
    expect(html.match(/disabled=""/g)).toHaveLength(1)
    expect(text(html)).toContain('hashicorp/terraform is already on the list as Terraform.')
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
    expect(text(renderToStaticMarkup(<ScheduleNote schedule={null} operator paused={false} />))).toBe('No schedule. Press Check now to check by hand. One approval covers all the upgrade tickets.')
    expect(text(renderToStaticMarkup(<ScheduleNote schedule={null} operator={false} paused={false} />))).toBe('No schedule. An Operator can press Check now to check by hand. One approval covers all the upgrade tickets.')
  })
})

describe('the count line under the title', () => {
  const page = (view: unknown, me: Me) => text(render(view, me, [], <AppRoutes context={{ name: me.display, now: new Date(), operator: me.roles.includes('operator') }} />))

  it('says what has a newer version, what can’t be checked and what isn’t checked yet, right under the title, to Operators and Approvers', () => {
    for (const me of [ALICE, BOB]) expect(page(statuses, me)).toContain('Software watchlist 3 have a newer version · 1 can’t be checked · 1 not checked yet')
  })

  it('keeps the plain lead while the list is empty', () => {
    expect(page(empty, ALICE)).toContain('Software watchlist Everything your team runs, in one list.')
  })
})

describe('what checks each row', () => {
  it('says each row is checked on GitHub, from the registry', () => {
    const words = text(render(statuses, ALICE))
    for (const row of (statuses as WatchlistView).software) expect(words).toContain(`${row.name} Checked on GitHub · ${row.source.ref}`)
  })

  it('never says a row is checked while the registry says GitHub is not working', () => {
    const down = capabilitiesFixture.capabilities.map((c) => (c.id === 'github.releases' ? { ...c, state: 'down' as const } : c))
    const words = text(render(statuses, ALICE, [], <SoftwareRoute />, { ...capabilitiesFixture, capabilities: down }))
    expect(words).toContain('LangGraph On GitHub · langchain-ai/langgraph')
    expect(words).not.toContain('Checked on GitHub')
  })
})

describe('after an Approver declines the latest check', () => {
  const view = { ...statuses, last_check: { run_id: rejectedRun.run_id, state: 'rejected', started_at: '2026-11-16T01:00:12Z' } }
  const record = /Declined by Bob\. Nothing was written\. Reason: Wrong version\. The tickets will be proposed again at the next check, [^.]+\./
  const rowsOf = (html: string) => html.split('<li id="software-').slice(1)

  it('gives the record, with the next check, on each row with a new version and on no other row', () => {
    for (const me of [ALICE, BOB]) {
      const noted = rowsOf(render(view, me, [rejectedRun])).filter((row) => record.test(text(row)))
      expect(noted.map((row) => /<b>([^<]+)<\/b>/.exec(row)?.[1])).toEqual(['LangGraph'])
    }
  })

  it('gives the same record in the history, on the line of the check that found the new version', () => {
    const langgraph = (statuses as WatchlistView).software.find((row) => row.status === 'behind')!
    const declined = 'Declined by Bob. Nothing was written. Reason: Wrong version. The tickets will be proposed again at the next check, Mon 16 Nov, 9:00.'
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <SoftwareHistory row={langgraph} nameOf={(id) => id} declined={declined} id="h" />
      </MemoryRouter>,
    )
    expect(text(html)).toContain(`Mon 16 Nov, 9:00 Found 1.2.16. ${declined}`)
    expect(html).not.toContain('href="/jira/')
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
        <SoftwareHistory row={row as WatchedSoftwareView} nameOf={(id) => id} declined={null} id="h" />
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


describe('a repository GitHub moved', () => {
  const rows = (moved as WatchlistView).software
  const fastapi = rows.find((row) => row.name === 'FastAPI')!
  const note = (changes: { confirming?: boolean; busy?: boolean; operator?: boolean } = {}) =>
    renderToStaticMarkup(<MovedNote row={fastapi} operator={changes.operator ?? true} confirming={changes.confirming ?? false} busy={changes.busy ?? false} onAsk={() => undefined} onConfirm={() => undefined} onCancel={() => undefined} />)
  const attention = (html: string) => html.slice(html.indexOf('needs-attention-heading'), html.indexOf('software-we-watch-heading'))
  const rowOf = (html: string, name: string) => html.split('<li id="software-').find((part) => part.includes(`<b>${name}</b>`)) ?? ''

  it('says on the row that GitHub renamed the project, still reaches it, and offers the new address to an Operator', () => {
    const html = render(moved, ALICE)
    const row = text(rowOf(html, 'FastAPI'))
    expect(row).toContain('Checked on GitHub · tiangolo/fastapi')
    expect(row).toContain('GitHub now calls this project fastapi/fastapi. We saved tiangolo/fastapi, and checks still reach it through GitHub’s redirect.')
    expect(buttons(rowOf(html, 'FastAPI'))).toContain('Use the new address for FastAPI')
    expect(row).toContain('New version')
  })

  it('lists the moved and the missing repository in Needs attention, each with a way to find its row', () => {
    const words = text(attention(render(moved, ALICE)))
    expect(words).toContain('Needs attention 2')
    expect(words).toContain('GitHub moved FastAPI from tiangolo/fastapi to fastapi/fastapi.')
    expect(words).toContain('GitHub can’t find langchain-ai/langserve, the address saved for LangServe.')
    expect(buttons(attention(render(moved, ALICE))).filter((label) => label.startsWith('Show it'))).toHaveLength(2)
    expect(words).not.toContain('Use the new address')
  })

  it('offers the new address once, on the row that was renamed and nowhere else', () => {
    const html = render(moved, ALICE)
    expect(buttons(html).filter((label) => label.startsWith('Use the new address'))).toEqual(['Use the new address for FastAPI'])
  })

  it('gives a repository GitHub cannot find its own words, no new address, and no promise it moved somewhere known', () => {
    const html = render(moved, ALICE)
    const row = text(rowOf(html, 'LangServe'))
    expect(row).toContain('Can’t check')
    expect(row).toContain('GitHub can’t find langchain-ai/langserve. It may have moved to another repository. LangServe stays Can’t check until GitHub finds that address. Remove it and add it again at its new address.')
    expect(row).not.toContain('Use the new address')
    expect(row).not.toContain('GitHub answered 404')
    expect(row).toContain('Remove LangServe')
  })

  it('tells an Approver, who cannot change the list, what an Operator can do', () => {
    const html = render(moved, BOB)
    const words = text(html)
    expect(words).toContain('An Operator can switch it to the new address.')
    expect(words).toContain('An Operator can fix this.')
    expect(buttons(html).some((label) => label.startsWith('Use the new address'))).toBe(false)
    expect(buttons(html).some((label) => label.startsWith('Remove'))).toBe(false)
  })

  it('asks once before it changes the list, says nothing is written outside, and offers Cancel', () => {
    const html = note({ confirming: true })
    expect(text(html)).toContain('Read FastAPI from fastapi/fastapi from now on? Only our list changes. Nothing is written to GitHub or Jira.')
    expect(buttons(html)).toEqual(['Yes, use fastapi/fastapi', 'Cancel'])
    expect(html).toContain('aria-labelledby="new-address-question-')
    expect(html).toContain('tabindex="-1"')
    expect(note()).not.toContain('Cancel')
  })

  it('holds a second press while the switch is sent, without moving focus off the button', () => {
    const html = note({ confirming: true, busy: true })
    expect(html).toMatch(/aria-busy="true"[^>]*>[\s\S]*Yes, use fastapi\/fastapi/)
    expect(html).toContain('aria-disabled="true"')
  })

  it('shows nothing where GitHub reported no move', () => {
    const plain = (statuses as WatchlistView).software[0]!
    expect(renderToStaticMarkup(<MovedNote row={plain} operator confirming={false} busy={false} onAsk={() => undefined} onConfirm={() => undefined} onCancel={() => undefined} />)).toBe('')
    expect(text(render(statuses, ALICE))).not.toContain('Use the new address')
  })

  it('leaves a row as it was before this fact existed when the platform sends neither field', () => {
    const older: Record<string, unknown> = { ...fastapi }
    delete older['moved_to']
    delete older['not_found']
    const html = render({ ...(statuses as WatchlistView), software: [older] }, ALICE)
    expect(text(html)).not.toContain('GitHub now calls')
    expect(text(html)).not.toContain('GitHub can’t find')
  })
})
