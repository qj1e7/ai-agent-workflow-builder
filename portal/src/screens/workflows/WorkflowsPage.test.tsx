import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import declinedWatchlist from '../../../../contracts/fixtures/builder/use-case.declined.json'
import { App } from '../../App'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import questionHome from '../../../../contracts/fixtures/builder/home.alice.question.json'
import declinedHome from '../../../../contracts/fixtures/builder/home.alice.declined-test.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import setupCardFixture from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import { cardFrom, draftContent } from '../home/card'
import draftsFixture from '../../../../contracts/fixtures/builder/drafts.json'
import peopleList from '../../../../contracts/fixtures/people/list.json'
import type { DraftView, HomeOut, Me, PersonOut, ReplyView, TeamRequestView, UnderstoodRowView, UseCaseView } from '../../api/types'
import type { LastRun } from './workflow'
import { needsTotal, pinnedOf } from '../home/home'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const CAROL: Me = { id: 'carol', display: 'Carol', roles: ['operator'] }
const TEAM = (peopleList.people as PersonOut[]).filter((person) => ['alice', 'bob', 'carol'].includes(person.id))

const WATCHLIST = watchlistUseCase as UseCaseView
const LANGGRAPH: UseCaseView = { ...(agentUseCase as UseCaseView), use_case_id: 'uc_lang', state: 'paused' }
const BUGS: UseCaseView = { ...(agentUseCase as UseCaseView), use_case_id: 'uc_bugs', name: 'Morning bug report check', instruction: 'Raise a ticket for each new bug report.' }
const lr = (change: Partial<LastRun>): LastRun => ({ run_id: 'run_x', state: 'succeeded', at: '2026-11-04T02:14:00Z', test: false, declined_by: null, decline_reason: null, approved_by: [], proposed: 0, written: 0, tickets: false, you_can_decide: false, retryable: false, reason: null, ...change })
const STOPPED_BUGS: UseCaseView = { ...BUGS, last_run: lr({ run_id: 'run_bugs', state: 'failed', retryable: true, reason: 'AgentError' }) }
const WAITING_WATCHLIST: UseCaseView = { ...WATCHLIST, last_run: lr({ run_id: 'run_01JB8', state: 'awaiting_approval', proposed: 1, tickets: true }) }
const DECLINED_WATCHLIST = declinedWatchlist as UseCaseView

const NOW = new Date('2026-11-04T15:00:00+08:00')

interface Setup {
  readonly me?: Me
  readonly useCases?: UseCaseView[] | Error | 'loading'
  readonly state?: unknown
  readonly home?: HomeOut
  readonly drafts?: DraftView[]
  readonly request?: { readonly id: string; readonly data?: TeamRequestView | Error }
  /** The page to open. Home reads the same Needs you, so a test can compare the two. */
  readonly path?: string
}

/** The platform answers for the person asking. In these tests only Bob may decide the waiting run. */
const asSeenBy = (me: Me, useCase: UseCaseView): UseCaseView =>
  useCase.last_run?.state === 'awaiting_approval' ? { ...useCase, last_run: { ...useCase.last_run, you_can_decide: me.id === 'bob' } } : useCase

function render({ me = ALICE, useCases = [STOPPED_BUGS, WAITING_WATCHLIST, LANGGRAPH], state, home, drafts, request, path = '/workflows' }: Setup = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  queryClient.setQueryData(['dev-users'], [ALICE, BOB, CAROL])
  queryClient.setQueryData(['people', scope], TEAM)
  queryClient.setQueryData(['capabilities', scope], capabilities)
  queryClient.setQueryData(['watchlist', scope], { software: [] })
  if (home) queryClient.setQueryData(['home', scope], home)
  if (drafts) queryClient.setQueryData(['drafts', scope], drafts)
  if (request?.data instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['team-request', scope, request.id] }).setState({ status: 'error', error: request.data, fetchStatus: 'idle' })
  else if (request?.data) queryClient.setQueryData(['team-request', scope, request.id], request.data)
  if (useCases instanceof Error) queryClient.getQueryCache().build(queryClient, { queryKey: ['use-cases', scope] }).setState({ status: 'error', error: useCases, fetchStatus: 'idle' })
  else if (useCases !== 'loading') queryClient.setQueryData(['use-cases', scope], useCases.map((useCase) => asSeenBy(me, useCase)))
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[{ pathname: path, search: request ? `?request=${request.id}` : '', state }]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const mainOf = (html: string) => /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
function rowOf(html: string, id: string): string {
  return new RegExp(`<li[^>]*data-workflow-id="${id}"[\\s\\S]*?</li>`).exec(html)?.[0] ?? ''
}

describe('the Workflows list', () => {
  const subOf = (html: string, id: string) => text(/<span[^>]*class="[^"]*sub[^"]*"[^>]*>[\s\S]*?<\/span>/.exec(rowOf(html, id))?.[0] ?? '')

  it('shows each workflow as its name, one line and one pill: Stopped, Waiting for a yes, On or Paused', () => {
    const html = render()
    const bugs = rowOf(html, 'uc_bugs')
    expect(bugs).toMatch(/data-life="on"[^>]*data-tone="bad"[^>]*>.*Stopped<\/span>/)
    expect(bugs).not.toMatch(/>On<\/span>/)
    expect(text(bugs)).toContain('Morning bug report check')
    const watchlist = rowOf(html, 'uc_01JB7')
    expect(watchlist).toMatch(/data-tone="wait"[^>]*>.*Waiting for a yes<\/span>/)
    const paused = rowOf(html, 'uc_lang')
    expect(paused).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
  })

  it('says each row’s schedule and its last run, as the sketch does', () => {
    const html = render({ useCases: [{ ...BUGS, schedule: { day: 'every_day', at: '08:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null }, last_run: lr({ state: 'failed', at: '2026-11-04T00:00:00Z', reason: 'AgentError' }) }] })
    expect(subOf(html, 'uc_bugs')).toBe('Daily 8:00 · last run today, an agent could not finish its work')
  })

  it('says no schedule and no runs yet for a workflow that never ran, with only the On or Paused pill', () => {
    const html = render({ useCases: [BUGS, LANGGRAPH] })
    expect(subOf(html, 'uc_bugs')).toBe('No schedule · no runs yet')
    expect(rowOf(html, 'uc_bugs')).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
  })

  it('names who declined, writes no ticket claim and gives no pill for it', () => {
    const html = render({ useCases: [DECLINED_WATCHLIST] })
    expect(subOf(html, 'uc_01JB7')).toMatch(/last run Thu 5 Nov, declined by Bob\. Nothing was written\.$/)
    expect(rowOf(html, 'uc_01JB7')).toMatch(/data-life="on"[^>]*>.*On<\/span>/)
    expect(text(rowOf(html, 'uc_01JB7'))).not.toContain('Test run')
  })

  it('marks a test run beside the status', () => {
    const tried = { ...BUGS, last_run: lr({ state: 'awaiting_approval', test: true, proposed: 1, tickets: true }) }
    const html = render({ useCases: [tried] })
    expect(subOf(html, 'uc_bugs')).toContain('last run today, waiting for a yes')
    expect(text(rowOf(html, 'uc_bugs'))).toContain('Test run')
  })

  it('shows Paused alone for a paused workflow, whatever its last run, and keeps that run in the line', () => {
    const html = render({ useCases: [{ ...STOPPED_BUGS, state: 'paused' }] })
    expect(rowOf(html, 'uc_bugs')).toMatch(/data-life="paused"[^>]*>.*Paused<\/span>/)
    expect(rowOf(html, 'uc_bugs')).not.toContain('Stopped</span>')
    expect(subOf(html, 'uc_bugs')).toMatch(/last run .*, an agent could not finish its work$/)
  })

  it('reads the same for an Approver as for an Operator', () => {
    expect(subOf(render({ me: BOB, useCases: [DECLINED_WATCHLIST] }), 'uc_01JB7')).toBe(subOf(render({ me: ALICE, useCases: [DECLINED_WATCHLIST] }), 'uc_01JB7'))
  })

  it('is one link for the whole row: the workflow’s page, and the Software page for the watchlist', () => {
    const html = render()
    expect(rowOf(html, 'uc_bugs')).toMatch(/<a[^>]*href="\/workflows\/uc_bugs"[^>]*>/)
    expect(rowOf(html, 'uc_01JB7')).toMatch(/<a[^>]*href="\/software"[^>]*>/)
    expect(rowOf(html, 'uc_bugs')).not.toContain('<button')
  })

  it('puts the rows that need you first, and puts a button in none of them', () => {
    const forCarol = render({ me: CAROL })
    expect([...forCarol.matchAll(/data-workflow-id="([^"]+)"/g)].map((m) => m[1])).toEqual(['uc_bugs', 'uc_01JB7', 'uc_lang'])
    const forBob = render({ me: BOB })
    expect([...forBob.matchAll(/data-workflow-id="([^"]+)"/g)].map((m) => m[1])).toEqual(['uc_01JB7', 'uc_bugs', 'uc_lang'])
    expect(text(rowOf(forBob, 'uc_01JB7'))).not.toContain('Review and decide')
    expect(text(rowOf(forCarol, 'uc_bugs'))).not.toContain('See why it stopped')
  })

  it('draws no agent faces and no step details in a row', () => {
    const main = mainOf(render())
    expect(main).not.toContain('data-state=')
    expect(main).not.toContain('/agents/')
  })

  it('has no lead sentence under the title, and no search or filters for a short list', () => {
    const main = mainOf(render())
    expect(main).not.toContain('find-workflows')
    expect(main).not.toContain('aria-pressed')
    expect(text(main)).not.toContain('The jobs that run by themselves')
  })

  it('offers the search and the filters once there are more than ten workflows', () => {
    const many = Array.from({ length: 11 }, (_, n) => ({ ...BUGS, use_case_id: `uc_n${String(n)}`, name: `Workflow ${String(n)}` }))
    const main = mainOf(render({ useCases: many }))
    expect(main).toContain('id="find-workflows"')
    expect(main).toContain('aria-pressed')
  })

  it('looks the same to an Approver, and has no change controls', () => {
    const main = text(mainOf(render({ me: BOB })))
    expect(main).toContain('Morning bug report check')
    expect(main).not.toMatch(/\bPause\b|\bResume\b|\bDelete\b|Run now/)
  })

  it('is read only for an Approver: one note names the Operators, and nothing changes anything or is dead', () => {
    const html = mainOf(render({ me: BOB }))
    expect(text(html).match(/Only Operators change/g)).toHaveLength(1)
    expect(text(html)).toContain('Only Operators change workflows. Ask Alice or Carol.')
    expect(html).not.toMatch(/disabled=""|aria-disabled="true"/)
    expect(text(html)).not.toMatch(/\bPause\b|\bResume\b|\bDelete\b|Run now|Discard|Change schedule/)
  })

  it('shows an Operator no such note, and an Approver none on an empty list, which says who sets workflows up', () => {
    expect(text(mainOf(render()))).not.toContain('Only Operators change')
    expect(text(mainOf(render({ me: CAROL })))).not.toContain('Only Operators change')
    expect(text(mainOf(render({ me: BOB, useCases: [] })))).not.toContain('Only Operators change')
  })

  it('says when there is nothing yet, in words for the person reading', () => {
    expect(text(mainOf(render({ useCases: [] })))).toContain('Nothing here yet Watch software on the Watchlist, or ask the Planner in the chat. Its checks show up here.')
    expect(text(mainOf(render({ useCases: [], me: BOB })))).toContain('Operators set up workflows, and you approve their changes.')
  })

  it('says the list could not be loaded and offers Try again', () => {
    const main = text(mainOf(render({ useCases: new ApiError(503, null) })))
    expect(main).toContain('The workflows could not be loaded.')
    expect(main).toContain('Try again')
  })
})

describe('after a delete', () => {
  const deleted = { deleted: { id: 'uc_gone', name: 'Stale ticket nudge' } }

  it('says what was deleted, with Undo and no time limit', () => {
    const html = render({ state: deleted })
    expect(text(html)).toContain('Deleted Stale ticket nudge.')
    expect(html).toMatch(/<button[^>]*id="toast-undo"[^>]*>Undo<\/button>/)
    expect(html).toContain('aria-label="Dismiss"')
  })

  it('tells the shell that the page moves focus itself, so focus can go to Undo', () => {
    const heading = (html: string) => /<h1\b[^>]*>/.exec(html)?.[0] ?? ''
    expect(heading(render({ state: deleted }))).toContain('data-page-moves-focus')
    expect(heading(render())).not.toContain('data-page-moves-focus')
  })

  it('draws the heading the same while the list loads and once it has loaded, so the shell’s focus stays on it', () => {
    const heading = (html: string) => /<h1\b[^>]*>[\s\S]*?<\/h1>/.exec(mainOf(html))?.[0] ?? ''
    for (const state of [undefined, deleted]) {
      const loading = render({ state, useCases: 'loading' })
      expect(text(mainOf(loading))).toContain('Loading the workflows')
      expect(heading(loading), JSON.stringify(state)).toBe(heading(render({ state })))
    }
  })

  it('shows no message on an ordinary visit', () => {
    expect(render()).not.toContain('toast-undo')
  })
})

const navNames = (html: string) =>
  [...html.matchAll(/<nav\b[^>]*aria-label="Browse"[^>]*>([\s\S]*?)<\/nav>/g)].flatMap((nav) => [...(nav[1] ?? '').matchAll(/<a\b([^>]*)>/g)].map((a) => /aria-label="([^"]*)"/.exec(a[1] ?? '')?.[1] ?? ''))
const primaries = (html: string) => (html.match(/<(?:a|button)\b[^>]*class="[^"]*_primary_[^"]*"[^>]*>/g) ?? []).length
const labelsOf = (html: string, ...label: string[]) => label.flatMap((words) => [...html.matchAll(new RegExp(`>${words}<`, 'g'))])

describe('Workflows has no button of its own to press', () => {
  it('keeps every row a link, and offers no primary button while Needs you lists a stopped run', () => {
    const html = render({ home: aliceHome as HomeOut, useCases: [{ ...WATCHLIST, last_run: lr({ run_id: 'run_01JB9', state: 'failed', retryable: true, reason: 'AgentError' }) }] })
    expect(primaries(mainOf(html))).toBe(0)
    expect(rowOf(html, 'uc_01JB7')).not.toMatch(/See why it stopped|Review and decide|Retry/)
  })

  it('lists the Approver’s approval once, as a row that opens its run', () => {
    const html = render({ me: BOB, home: bobHome as HomeOut })
    expect(primaries(mainOf(html))).toBe(0)
    expect(mainOf(html)).toMatch(/data-home-item="approval:[^"]+"/)
    expect(labelsOf(html, 'Review and decide')).toHaveLength(0)
  })
})

describe('Needs you at the top of Workflows', () => {
  const HOME = aliceHome as HomeOut

  it('lists what needs the person in full as plain rows, each ending in a chevron, with the tab’s total beside them', () => {
    const html = render({ home: HOME })
    const total = needsTotal(HOME)
    const section = /<section[^>]*aria-labelledby="[^"]*"[\s\S]*?<\/section>/.exec(html)?.[0] ?? ''
    expect(text(section)).toContain('Needs you')
    expect(section).toContain('data-home-item="stopped:run_01JB9"')
    expect(navNames(html).filter((name) => name.startsWith('Workflows'))).toEqual([`Workflows, ${String(HOME.workflows)} in all`])
    expect(html.indexOf('>Needs you</h2>')).toBeLessThan(html.indexOf('aria-label="Workflows"'))
    expect([...section.matchAll(/data-home-item="/g)]).toHaveLength(total)
  })

  it('says what stopped, in the sketch’s words, and opens the run', () => {
    const html = mainOf(render({ home: HOME }))
    expect(html).toMatch(/<a[^>]*href="\/runs\/run_01JB9"[^>]*>[\s\S]*?<b>Software watchlist<\/b> stopped (at |\w{3} \d+ \w{3} at )\d+:\d\d/)
  })

  it('says software GitHub can’t find, and opens that software’s own page', () => {
    const html = mainOf(render({ home: HOME }))
    const address = (HOME.addresses[0] as { software_id: string }).software_id
    expect(html).toContain(`href="/software/${address}"`)
  })

  it('groups the list into Do now and Set up, as Home does, with the same rows in each', () => {
    const html = mainOf(render({ home: HOME }))
    const names = [...html.matchAll(/<h3 id="[^"]*">(Do now|Set up)<\/h3>/g)].map((m) => m[1])
    expect(names).toEqual(['Do now', 'Set up'])
    const keys = [...html.matchAll(/data-home-item="([^"]+)"/g)].map((m) => m[1])
    expect(keys.indexOf('stopped:run_01JB9')).toBeLessThan(keys.indexOf('address:' + (HOME.addresses[0] as { software_id: string }).software_id))
    expect(keys).toHaveLength(needsTotal(HOME))
  })

  it('shows no section when nothing needs the person', () => {
    const quiet: HomeOut = { ...HOME, approvals: [], approvals_total: 0, confirmations: [], stopped: [], stopped_total: 0, replied: [], connections: [], addresses: [] }
    expect(render({ home: quiet })).not.toContain('>Needs you</h2>')
    expect(render()).not.toContain('>Needs you</h2>')
  })

  /** Every kind of need at once: Alice's stop, connections, addresses and reply, Bob's approval and confirmations, a question and a declined test run. */
  const EVERY_KIND: HomeOut = {
    ...HOME,
    approvals: (bobHome as HomeOut).approvals,
    approvals_total: (bobHome as HomeOut).approvals_total,
    confirmations: (bobHome as HomeOut).confirmations,
    questions_for_me: (questionHome as HomeOut).questions_for_me,
    questions_for_me_total: (questionHome as HomeOut).questions_for_me_total,
    declined: (declinedHome as HomeOut).declined,
    declined_total: (declinedHome as HomeOut).declined_total,
  }
  const rowsOfNeeds = (html: string) =>
    Object.fromEntries(
      [...mainOf(html).matchAll(/<li data-home-item="([^"]+)" data-kind="([^"]+)" data-tone="([^"]+)">([\s\S]*?)<\/li>/g)].map((m) => [m[1] ?? '', { kind: m[2] ?? '', tone: m[3] ?? '', words: text(m[4] ?? '') }]),
    )

  it('says every kind of need in the same words and tone as Home', () => {
    const onWorkflows = rowsOfNeeds(render({ me: BOB, home: EVERY_KIND }))
    const onHome = rowsOfNeeds(render({ me: BOB, home: EVERY_KIND, path: '/' }))
    expect(new Set(Object.values(onWorkflows).map((row) => row.kind))).toEqual(new Set(['stopped', 'approval', 'connection', 'address', 'confirmation', 'declined', 'question', 'reply']))
    expect(Object.keys(onWorkflows)).toHaveLength(needsTotal(EVERY_KIND))
    expect(onWorkflows).toEqual(onHome)
  })

  it('says the rows the review found in two words in Home’s words, and colours an address amber, as Home and the sketch do', () => {
    const rows = Object.values(rowsOfNeeds(render({ home: EVERY_KIND })))
    const words = rows.map((row) => row.words)
    expect(words).toEqual(expect.arrayContaining(['Jira isn’t answering', 'GitHub key expires Wed 18 Nov', 'FastAPI moved to fastapi/fastapi on GitHub', 'Dave waits to be confirmed as an Approver', 'LangServe can’t be found on GitHub']))
    expect(rows.filter((row) => row.kind === 'address').map((row) => row.tone)).toEqual(['wait', 'wait'])
  })

  it('lists the same needs the strip counts, so the strip’s “N more” plus its one row is the number of rows here', () => {
    const html = mainOf(render({ home: HOME, drafts: draftsFixture.drafts }))
    const needsYou = /<section[^>]*>\s*<h2[^>]*>Needs you<\/h2>[\s\S]*?<\/section>/.exec(html)?.[0] ?? ''
    expect([...needsYou.matchAll(/data-home-item="/g)]).toHaveLength((pinnedOf(HOME)?.more ?? -1) + 1)
    expect(needsYou, 'a draft is listed under All workflows, which the strip does not count').not.toContain('data-draft=')
  })
})


const REPLY: ReplyView = { replied_by: 'bob', replied_by_name: 'Bob', replied_at: '2026-11-04T08:30:00Z', text: 'Looking into it.', status: 'answered' }
const REQUEST: TeamRequestView = {
  request_id: 'trq_01JD5RP',
  kind: 'support',
  about: { run_id: 'run_01JB9' },
  note: 'It stopped again.',
  asked_by: 'alice',
  asked_by_name: 'Alice',
  asked_at: '2026-11-04T07:02:00Z',
  status: 'answered',
  replies: [REPLY],
  posted_to_teams: true,
  not_posted_because: null,
}
const sectionOf = (html: string, name: string) => new RegExp(`<section[^>]*data-section="${name}"[\\s\\S]*?</section>`).exec(html)?.[0] ?? ''

describe('the rest of the page under Needs you', () => {
  const HOME = aliceHome as HomeOut
  const DRAFTS = draftsFixture.drafts as DraftView[]

  it('come in order: Needs you, All workflows with its drafts after the workflows, Following up', () => {
    const html = mainOf(render({ home: HOME, drafts: DRAFTS }))
    const at = ['>Needs you</h2>', 'aria-labelledby="all-workflows-h"', 'data-workflow-id="', 'data-draft="', 'data-section="following"'].map((marker) => html.indexOf(marker))
    expect(at.every((index) => index >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
  })

  it('has no Waiting on others, because a waiting workflow reads Waiting for a yes in its row', () => {
    expect(mainOf(render({ home: HOME }))).not.toContain('Waiting on others')
  })

  it('lists a draft under All workflows as a row like a workflow’s, with the pill Draft, one link that opens it in the chat, where its card has Discard', () => {
    const html = mainOf(render({ home: HOME, drafts: DRAFTS }))
    const draft = /<li[^>]*data-draft="drf-7f3a2c"[\s\S]*?<\/li>/.exec(html)?.[0] ?? ''
    expect(text(draft)).toBe('Nudge stale tickets Only your words are saved. Last saved Today, 14:24. Draft')
    expect(draft).toMatch(/<a[^>]*href="\/\?draft=drf-7f3a2c"/)
    expect(draft).not.toContain('<button')
    expect(html.indexOf('data-draft=')).toBeGreaterThan(html.indexOf('aria-label="Workflows"'))
  })


  it('gives a saved card’s draft the reason setupLeft gives, the same words as the card’s footer', () => {
    const card = cardFrom('Weekly summary', setupCardFixture.rows as UnderstoodRowView[], 'Every Friday, sum up the closed tickets')
    const saved: DraftView = { ...(DRAFTS[0] as DraftView), step: null, content: draftContent(card, null) }
    const html = mainOf(render({ home: HOME, drafts: [saved] }))
    expect(text(html)).toContain('Needs when it runs and the Planner to choose the agents. Last saved')
    expect(text(html)).not.toContain('Step ')
  })

  it('shows no draft without drafts, and none to an Approver who is not an Operator', () => {
    expect(render({ home: HOME, drafts: [] })).not.toContain('data-draft=')
    expect(render({ me: BOB, home: bobHome as HomeOut, drafts: DRAFTS })).not.toContain('data-draft=')
  })

  it('lists the person’s requests under Following up with the status and the latest reply, each opening that request', () => {
    const following = sectionOf(mainOf(render({ home: HOME })), 'following')
    expect(text(following)).toContain('It stopped again. Platform problem')
    expect(text(following)).toContain('Answered by Bob: Looking into it.')
    expect(following).toContain('href="/workflows?request=trq_01JD5RP"')
  })

  it('says how many requests Following up shows when there are more than the platform lists, and never offers a link that goes nowhere', () => {
    const many: HomeOut = { ...HOME, following_up_total: 63 }
    const html = render({ home: many })
    expect(text(sectionOf(mainOf(html), 'following'))).toContain('Showing the newest 1 of 63.')
    expect(text(sectionOf(mainOf(render({ home: HOME })), 'following'))).not.toContain('Showing the newest')
  })

  it('shows a reply the person has not opened in Needs you', () => {
    const html = render({ home: HOME })
    expect(mainOf(html)).toContain('data-home-item="reply:trq_01JD5RP"')
    expect(text(mainOf(html))).toContain('Bob replied to your report')
    expect(mainOf(html)).toMatch(/<li[^>]*data-home-item="reply:trq_01JD5RP"[^>]*><a[^>]*href="\/workflows\?request=trq_01JD5RP"/)
    expect(navNames(html).filter((name) => name.startsWith('Workflows'))).toEqual([`Workflows, ${String(HOME.workflows)} in all`])
  })

  it('leaves a request in Following up but not in Needs you once the person has opened it', () => {
    const opened: HomeOut = { ...HOME, replied: [] }
    const html = mainOf(render({ home: opened }))
    expect(html).not.toContain('reply:trq_01JD5RP')
    expect(html).toContain('data-request="trq_01JD5RP"')
  })
})

describe('a request opened by its link', () => {
  const open = (setup: Setup) => mainOf(render({ home: aliceHome as HomeOut, ...setup, request: { id: 'trq_01JD5RP', ...setup.request } }))

  it('shows the request, who asked, the replies and a reply form to anyone on the team', () => {
    for (const me of [BOB, CAROL]) {
      const html = open({ me, request: { id: 'trq_01JD5RP', data: REQUEST } })
      expect(text(html)).toContain('Alice reported a platform problem')
      expect(text(html)).toContain('It stopped again.')
      expect(text(html)).toContain('Bob')
      expect(text(html)).toContain('Looking into it.')
      expect(html).toContain('href="/runs/run_01JB9"')
      expect(html).toMatch(/<label[^>]*>Your reply<\/label>/)
      expect(html).toMatch(/<button[^>]*>Send reply<\/button>/)
    }
  })

  it('offers someone else Answered, and Done for when nothing more will happen', () => {
    const html = open({ me: BOB, request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).toMatch(/<input[^>]*type="radio"[^>]*checked=""[^>]*\/>Answered/)
    expect(text(html)).toContain('Done, nothing more will happen')
  })

  it('speaks to the asker as you, and offers her only Add and Mark done', () => {
    const html = open({ me: ALICE, request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(text(html)).toContain('You reported a platform problem')
    expect(text(html)).not.toContain('Alice reported')
    expect(text(html)).toContain('Add to your request')
    expect(html).toMatch(/<button[^>]*>Add<\/button>/)
    expect(html).toMatch(/<button[^>]*>Mark done<\/button>/)
    expect(html).not.toContain('type="radio"')
    expect(html).not.toContain('Send reply')
  })

  it('shows an Approver no note about changing workflows on a request, which is not the list', () => {
    expect(text(open({ me: BOB, request: { id: 'trq_01JD5RP', data: REQUEST } }))).not.toContain('Only Operators change')
  })

  it('labels the asker’s own note as an addition, never as an answer', () => {
    const noted: TeamRequestView = { ...REQUEST, status: 'open', replies: [{ ...REQUEST.replies[0]!, replied_by: 'alice', replied_by_name: 'Alice', status: 'added' }] }
    const html = open({ me: BOB, request: { id: 'trq_01JD5RP', data: noted } })
    expect(text(html)).toContain('Added to the request')
    expect(text(html)).not.toMatch(/· Answered/)
  })

  it('replaces the list while it is open, and offers the way back', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).not.toContain('aria-label="Workflows"')
    expect(html).not.toContain('aria-label="Needs you"')
    expect(html).toMatch(/<a[^>]*href="\/workflows"[^>]*>[\s\S]*Workflows<\/a>/)
  })

  it('says plainly when the id is unknown, without a Try again', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: new ApiError(404, null) } })
    expect(text(html)).toContain('There is no request with that link')
    expect(html).not.toContain('Try again')
  })

  it('offers Try again when the platform did not answer', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: new ApiError(503, null) } })
    expect(text(html)).toContain('The request could not be loaded')
    expect(html).toContain('Try again')
  })

  it('says when the card did not reach Teams, and when nobody has replied', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: { ...REQUEST, replies: [], status: 'open', posted_to_teams: false, not_posted_because: 'no_channel' } } })
    expect(text(html)).toContain('Nobody has replied yet.')
    expect(text(html)).toContain('No Teams channel is set up')
  })

  it('has nothing on it that approves', () => {
    const html = open({ request: { id: 'trq_01JD5RP', data: REQUEST } })
    expect(html).not.toMatch(/Approve|Decline|Review and decide/)
  })
})
