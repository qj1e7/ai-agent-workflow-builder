import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import drafting from '../../../../contracts/fixtures/builder/drafted.drafting.json'
import notDrafted from '../../../../contracts/fixtures/builder/drafted.not-drafted.json'
import question from '../../../../contracts/fixtures/builder/drafted.question.json'
import ready from '../../../../contracts/fixtures/builder/drafted.ready.json'
import setUp from '../../../../contracts/fixtures/builder/drafted.set-up.json'
import simulated from '../../../../contracts/fixtures/builder/drafted.simulated.json'
import simulating from '../../../../contracts/fixtures/builder/drafted.simulating.json'
import waiting from '../../../../contracts/fixtures/builder/drafted.waiting.json'
import draftUseCase from '../../../../contracts/fixtures/builder/use-case.draft.json'
import bobSetUp from '../../../../contracts/fixtures/builder/setup-approval.bob.json'
import carolSetUp from '../../../../contracts/fixtures/builder/setup-approval.carol.json'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import { ApiProvider } from '../../api/context'
import { draftedKey, stillMoving } from '../../api/draftedQueries'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { CantReply, DraftedWorkflowView, ExplainSetting, Me, PartReply, PlannerReply, RefinementView, SetupCardReply, SetUpApprovalView, UseCaseView } from '../../api/types'
import { holdTurnOn } from '../../api/workflowQueries'
import { Answer, type Page } from '../home/AnswerCards'
import { ChatProvider } from '../home/ChatProvider'
import { CardLive } from '../home/primary'
import { DraftedCard } from './DraftedCard'
import { CHANGED_SINCE_CHECK } from './drafted'
import { REFINE_IT, REFINE_NEVER, roundWords } from './Refinement'
import { SetUpApproval } from './SetUpApprovalPage'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const WORDS = 'Draft an n8n workflow that every Monday at 9:00 checks langchain-ai/langgraph for a new release and raises a ticket in MOCK'
const scope = createDevSession(null).cacheScope()
const BOB: Me = { id: 'u_bob', display: 'Bob', roles: ['approver'] }

function render(node: React.ReactNode, { me, view, useCase, pressed = false }: { me?: Me; view?: DraftedWorkflowView; useCase?: UseCaseView; pressed?: boolean } = {}): string {
  const queryClient = new QueryClient()
  if (me) queryClient.setQueryData(['me', scope], me)
  if (view) queryClient.setQueryData(draftedKey(scope, view.drafted_id), view)
  if (useCase) queryClient.setQueryData(keys.useCase(scope, useCase.use_case_id), useCase)
  if (useCase && pressed) holdTurnOn(queryClient, scope, useCase.use_case_id, Date.now(), 'k1')
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <ChatProvider>{node}</ChatProvider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&quot;', '"').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const card = (view: DraftedWorkflowView, revision = view.card_revision) => render(<DraftedCard draftedId={view.drafted_id} revision={revision} />, { view })
const SET_UP = setUp as DraftedWorkflowView
/** The workflow the approved revision was set up as, still a Draft. */
const SET_UP_DRAFT: UseCaseView = { ...(draftUseCase as UseCaseView), use_case_id: 'uc_01JDRAFTRELEASE', name: 'Release check' }
const setUpCard = (useCase: UseCaseView, pressed = false) => render(<DraftedCard draftedId={SET_UP.drafted_id} revision={SET_UP.card_revision} />, { view: SET_UP, useCase, pressed })
const CHECK = 'An Approver checks it once before it first runs.'
const TURN_ON_NOW = 'Press Turn on. I do a test run, which writes nothing, and turn it on if the test passes.'

describe('the drafted workflow card', () => {
  it('shows Drafting with time going while the drafter works, and no steps the platform did not report', () => {
    const html = card(drafting as DraftedWorkflowView)
    expect(text(html)).toContain('Drafting it as an n8n workflow')
    expect(text(html)).toContain('Revision 1 Drafting')
    expect(html).not.toContain('aria-label="Steps"')
    expect(buttons(html)).toEqual([])
  })

  it('reads like any set-up card: its steps, In short, what was added, one line for the one-time check, and Turn on, leaving Start from the Portal out', () => {
    const html = card(ready as DraftedWorkflowView)
    const words = text(html)
    expect(words).toContain('Release check')
    expect(words).toContain('Revision 2 Draft')
    expect(words).toContain('Every Monday')
    expect(words).not.toContain('Start from the Portal')
    expect(html).toContain('data-in-short')
    expect(words).toMatch(/Added \d+ things? every workflow needs\./)
    expect(html).toContain('data-check')
    expect(words.split(CHECK)).toHaveLength(2)
    expect(buttons(html)).toEqual(['Ask for a change', 'Edit in n8n', 'Turn on'])
    expect(words).not.toContain('Send for approval')
  })

  it('puts the reason where Turn on would be when the check cannot be asked for, never a dead button', () => {
    const html = card(question as DraftedWorkflowView)
    expect(text(html)).toContain('Answer 2 questions first')
    expect(text(html)).toContain(CHECK)
    expect(buttons(html)).toEqual(expect.not.arrayContaining(['Turn on', 'Send for approval']))
    expect(buttons(html).at(-1)).toBe('Edit in n8n')
    expect(html).not.toContain('disabled')
  })

  it('after a refused set-up, it is a draft again: it says why, and offers Turn on and Ask for a change', () => {
    const refused = {
      ...(setUp as DraftedWorkflowView),
      state: 'draft',
      can_send: true,
      why_not_send: null,
      set_up: { state: 'refused', use_case_id: null, words: CHANGED_SINCE_CHECK },
    } as DraftedWorkflowView
    const html = card(refused)
    expect(text(html)).toContain('Revision 2 Draft')
    expect(text(html)).toContain('Changed since it was approved. Press Turn on to ask for the check again.')
    expect(buttons(html)).toEqual(['Ask for a change', 'Turn on'])
  })

  it('after n8n did not take it, it says so and offers Try again beside Turn on and Ask for a change', () => {
    const failed = {
      ...(setUp as DraftedWorkflowView),
      state: 'draft',
      can_send: true,
      why_not_send: null,
      set_up: { state: 'failed', use_case_id: null, words: 'n8n didn’t take it, so it isn’t set up yet. Try again.' },
    } as DraftedWorkflowView
    const html = card(failed)
    expect(text(html)).toContain('n8n didn’t take it, so it isn’t set up yet. Try again.')
    expect(buttons(html)).toEqual(['Try again', 'Ask for a change', 'Turn on'])
  })

  it('lists its flags under a disclosure, with no See the report and no Explain', () => {
    const flag = { rule: 'operation_off', block: 'Open an issue', what: 'Changes data with one of n8n’s own blocks', why: 'n8n’s own blocks don’t ask for approval on each run.', clears: 'approver_may_accept', takes: 'An Approver may accept it at set-up.' } as const
    const base = ready as DraftedWorkflowView
    const flagged = { ...base, flags: 1, report: base.report === null ? null : { ...base.report, flags: [flag] } } as DraftedWorkflowView
    const html = card(flagged)
    const flags = /<details\b[\s\S]*?<\/details>/.exec(html)?.[0] ?? ''
    expect(flags, 'closed until opened').not.toMatch(/<details[^>]*\bopen/)
    expect(text(flags)).toMatch(/^1 flag\. See them /)
    expect(text(flags)).toContain(flag.what)
    expect(text(flags), 'where, as the block’s own name').toMatch(/In “Open an issue” ?\./)
    expect(buttons(html)).not.toContain('See the report')
    expect(text(html)).not.toMatch(/\bExplain\b/)
  })

  it('once Turn on asked for the check, it stays a Draft that waits for an Approver to check it, with no button its author could press', () => {
    const html = card(waiting as DraftedWorkflowView)
    expect(text(html)).toContain('Revision 2 Draft')
    expect(text(html)).not.toContain('Waiting for approval')
    expect(text(html)).toContain('Waiting for an Approver to check it.')
    expect(text(html)).toContain(CHECK)
    expect(buttons(html), 'nothing for its author to press').toEqual([])
  })

  it('after the yes, it says who checked it and offers Turn on again, beside Open it', () => {
    const html = setUpCard(SET_UP_DRAFT)
    const words = text(html)
    expect(words).toContain('Revision 2 Draft')
    expect(words).toContain('Bob checked it once.')
    expect(words).not.toContain(CHECK)
    expect(words).toContain(TURN_ON_NOW)
    expect(buttons(html)).toEqual(['Turn on', 'Open it'])
    expect(html).toContain('href="/workflows/uc_01JDRAFTRELEASE"')
  })

  it('once Turn on is pressed after the yes, the card is the set-up card: the test run, then on', () => {
    const html = setUpCard(SET_UP_DRAFT, true)
    expect(text(html)).toContain('Release check')
    expect(text(html)).toContain('Building')
    expect(text(html)).not.toContain('Revision 2')
    expect(buttons(html)).not.toContain('Turn on')
  })

  it('offers Turn on only once the platform says the workflow it was set up as is a Draft, never while unread or gone', () => {
    const html = render(<DraftedCard draftedId={SET_UP.drafted_id} revision={SET_UP.card_revision} />, { view: SET_UP })
    expect(text(html)).toContain('Bob checked it once.')
    expect(text(html)).not.toContain(TURN_ON_NOW)
    expect(buttons(html)).toEqual(['Open it'])
  })

  it('reads On once the workflow is on, with nothing left to press but Open it', () => {
    const html = setUpCard({ ...SET_UP_DRAFT, state: 'on' })
    expect(text(html)).toContain('Revision 2 On')
    expect(text(html)).toContain('Bob checked it once.')
    expect(text(html)).not.toContain(TURN_ON_NOW)
    expect(buttons(html)).toEqual(['Open it'])
  })

  it('says it is setting it up while n8n has not taken it, and shows the failure with Try again', () => {
    const base = setUp as DraftedWorkflowView
    expect(text(card({ ...base, set_up: { state: 'setting_up', use_case_id: null, words: null } }))).toContain('Setting it up in n8n.')
    const failed = card({ ...base, set_up: { state: 'failed', use_case_id: null, words: 'n8n did not answer.' } })
    expect(text(failed)).toContain('n8n did not answer.')
    expect(buttons(failed)).toContain('Try again')
    const refused = card({ ...base, set_up: { state: 'refused', use_case_id: null, words: 'It changed after it was approved.' } })
    expect(text(refused)).toContain('It changed after it was approved.')
    expect(buttons(refused)).not.toContain('Try again')
  })

  it('says it was declined, by whom and why, and that nothing was set up', () => {
    const base = waiting as DraftedWorkflowView
    const html = card({ ...base, state: 'declined', approval: { ...base.approval!, status: 'declined', decided_by: 'Bob', reason: 'Wrong project or channel' } })
    expect(text(html)).toContain('Revision 2 Draft')
    expect(text(html)).toContain('Declined by Bob: wrong project or channel. Nothing was set up.')
  })

  it('says a new revision cancelled the waiting approval', () => {
    expect(text(card({ ...(ready as DraftedWorkflowView), replaced_waiting: true }))).toContain('This revision cancelled the waiting approval.')
  })

  it('settles an older revision into one line', () => {
    const html = card({ ...(ready as DraftedWorkflowView), card_revision: 2 }, 1)
    expect(text(html)).toContain('Revision 1. Revision 2 is below.')
    expect(buttons(html)).toEqual([])
  })

  it('says why it was not drafted, with Ask the team', () => {
    const html = card(notDrafted as DraftedWorkflowView)
    expect(text(html)).toContain('I couldn\'t draft that.')
    expect(buttons(html)).toEqual(['Ask the team'])
  })
})

describe('the drafted card’s simulation (ADR 0054, PR 7)', () => {
  const STILL_TESTS = 'Turn on still runs the real test, which writes nothing.'

  it('leads with the result, then what failed: code’s grade first and the AI’s note after it, as help', () => {
    const view = simulated as DraftedWorkflowView
    const words = text(card(view))
    const lead = 'Tried 5 cases on practice systems: 4 passed.'
    expect(words).toContain(lead)
    const failed = view.simulation!.cases.find((c) => c.verdict === 'failed')!
    const at = (s: string) => words.indexOf(s)
    expect(at(lead)).toBeLessThan(at('Failed Source not found'))
    expect(at('Failed Source not found')).toBeLessThan(at(`Expected: ${failed.expected}`))
    expect(at(`Expected: ${failed.expected}`)).toBeLessThan(at(`What happened: ${failed.happened}`))
    expect(at(`What happened: ${failed.happened}`)).toBeLessThan(at(`The AI’s note: ${failed.note!}`))
    expect(words).toContain('A failed case doesn’t stop Turn on. You decide.')
    expect(words).toContain(STILL_TESTS)
  })

  it('shows a case no block could play as Not tried, never as passed', () => {
    const words = text(card(simulated as DraftedWorkflowView))
    expect(words).toContain('Not tried Timeout')
    expect(words).not.toContain('Passed Timeout')
    expect(words).toContain('Passed Happy path')
  })

  it('never blocks Turn on: a failed case leaves the same buttons as no simulation at all', () => {
    expect(buttons(card(simulated as DraftedWorkflowView))).toEqual(buttons(card(ready as DraftedWorkflowView)))
    expect(buttons(card(simulated as DraftedWorkflowView)).at(-1)).toBe('Turn on')
  })

  it('names the blocks no case could try', () => {
    const view = simulated as DraftedWorkflowView
    const sim = { ...view.simulation!, not_tried: [{ block: 'Post the notice', why: 'No mock runs for it, so its output is pinned.' }] }
    expect(text(card({ ...view, simulation: sim }))).toContain('Not tried in any case: “Post the notice”. No mock runs for it, so its output is pinned.')
  })

  it('says so while it runs, with each case’s time limit, and claims no result', () => {
    const words = text(card(simulating as DraftedWorkflowView))
    expect(words).toContain('Trying it on practice systems. Each case can take up to 2 minutes.')
    expect(words).not.toContain('passed')
    expect(words).not.toContain(STILL_TESTS)
  })

  it('says simulation isn’t available here where there is no simulation n8n, and claims no result', () => {
    const words = text(card(ready as DraftedWorkflowView))
    expect(words).toContain('Simulation on practice systems isn’t available here.')
    expect(words).toContain(STILL_TESTS)
    expect(words).not.toContain('Tried')
    expect(words).not.toContain('Trying it')
  })

  it('says why nothing was tried, and offers Try again only to whoever can start it, never a dead button', () => {
    const view = simulated as DraftedWorkflowView
    const notRun = { ...view.simulation!, state: 'not_run' as const, tried: 0, passed: 0, cases: [], said: 'The practice systems didn\'t answer, so nothing was tried.', can_try_again: true }
    const html = card({ ...view, simulation: notRun })
    expect(text(html)).toContain('The practice systems didn\'t answer, so nothing was tried.')
    expect(buttons(html)).toContain('Try again')
    const bob = card({ ...view, simulation: { ...notRun, can_try_again: false } })
    expect(buttons(bob)).not.toContain('Try again')
    expect(bob).not.toContain('disabled')
  })

  it('never shows running past the limit: it says it didn’t finish, with Try again', () => {
    const view = simulating as DraftedWorkflowView
    const html = card({ ...view, simulation: { ...view.simulation!, state: 'not_finished', can_try_again: true } })
    expect(text(html)).toContain('It didn’t finish on practice systems in time, so there is no result.')
    expect(text(html)).not.toContain('Trying it')
    expect(buttons(html)).toContain('Try again')
  })

  it('says a revision was never tried, and offers Try it now, not Try again, to whoever can start it', () => {
    const view = simulating as DraftedWorkflowView
    const never = { ...view.simulation!, state: 'not_started' as const, started_at: null, can_try_again: true }
    const html = card({ ...view, simulation: never })
    expect(text(html)).toContain('It hasn’t been tried on practice systems yet.')
    expect(buttons(html)).toContain('Try it now')
    expect(buttons(html)).not.toContain('Try again')
    expect(buttons(card({ ...view, simulation: { ...never, can_try_again: false } }))).not.toContain('Try it now')
  })

  it('says a revision still needing a setting will be tried once every setting is filled, never not available and never running', () => {
    const html = card(question as DraftedWorkflowView)
    const words = text(html)
    expect(words).toContain('It will be tried on practice systems once every setting is filled.')
    expect(words).not.toContain('isn’t available')
    expect(words).not.toContain('Trying it')
    expect(html).not.toContain('role="status" data-simulation')
    expect(buttons(html)).not.toContain('Try it now')
  })
})

describe('refining the drafted card’s Check (ADR 0054, section 7, PR 8)', () => {
  const view = simulated as DraftedWorkflowView
  const refinement = (over: Partial<RefinementView>): RefinementView => ({ state: 'offered', said: 'A case failed on practice systems. I can change the draft where it failed and try it again.', rounds: [], revision: null, ends_by: null, can_start: true, ...over })
  const with_ = (over: Partial<RefinementView>) => card({ ...view, refinement: refinement(over) })

  it('offers Refine it to whoever can start it, after the result, and says nothing turns on', () => {
    const html = with_({})
    const words = text(html)
    expect(words.indexOf('Tried 5 cases on practice systems: 4 passed.')).toBeLessThan(words.indexOf('A case failed on practice systems.'))
    expect(words).toContain(REFINE_NEVER)
    expect(buttons(html)).toContain(REFINE_IT)
    expect(buttons(html).at(-1)).toBe('Turn on')
  })

  it('never shows a dead button: no Refine it for someone who can’t start it', () => {
    const html = with_({ can_start: false })
    expect(buttons(html)).not.toContain(REFINE_IT)
    expect(html).not.toContain('disabled')
  })

  it('says so while it refines, with each round as code counted it, and no button', () => {
    const html = with_({ state: 'refining', said: 'Refining it on practice systems.', rounds: [{ round: 1, passed: 1, scenarios: 2 }], can_start: false })
    expect(text(html)).toContain('Refining it on practice systems. Round 1: 1 of 2 cases passed.')
    expect(html).toContain('role="status"')
    expect(buttons(html)).not.toContain(REFINE_IT)
  })

  it('shows a refined draft and a refinement that gave up in the platform’s own words', () => {
    expect(text(with_({ state: 'refined', said: 'Refined on practice systems in 1 round. It’s checked again like any draft.', revision: 3, can_start: false }))).toContain('Refined on practice systems in 1 round.')
    const gaveUp = text(with_({ state: 'gave_up', said: 'I couldn’t refine it. A change didn’t make more cases pass.', can_start: false }))
    expect(gaveUp).toContain('I couldn’t refine it. A change didn’t make more cases pass.')
  })

  it('keeps reading the card while it refines', () => {
    expect(stillMoving({ ...view, refinement: refinement({ state: 'refining', can_start: false }) })).toBe(true)
    expect(stillMoving({ ...view, refinement: refinement({ state: 'gave_up', can_start: false }) })).toBe(false)
  })

  it('words each round plainly', () => {
    expect(roundWords({ round: 2, passed: 1, scenarios: 1 })).toBe('Round 2: 1 of 1 case passed.')
  })
})

describe('Build it with any n8n block', () => {
  const ANY_BLOCK = 'Build it with any n8n block'
  const cantWith = (words: string | null): CantReply => ({ ...(cant as CantReply), draft_words: words })
  const partWith = (words: string | null): PartReply => ({ ...(part as PartReply), draft_words: words })
  const cardWith = (words: string | null): SetupCardReply => ({ ...(setupCard as SetupCardReply), similar: null, draft_words: words })
  const draw = (reply: PlannerReply, me?: Me) => render(<Answer reply={reply} typed="x" page={PAGE} />, me ? { me } : {})
  const link = (html: string) => [...html.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)].find((m) => m[2] === ANY_BLOCK)?.[1] ?? null

  it('shows for an Operator as a quiet link on a set-up card, a part card and a can’t answer that carry words to draft', () => {
    for (const reply of [cardWith(WORDS), partWith(WORDS), cantWith(WORDS)]) {
      const html = draw(reply)
      expect(buttons(html)).toContain(ANY_BLOCK)
      expect(link(html)).toMatch(/class="[^"]*linkButton/)
    }
  })

  it('replaces Draft it as an n8n workflow and its note, so the person never picks a path', () => {
    for (const reply of [cardWith(WORDS), partWith(WORDS), cantWith(WORDS)]) {
      const html = draw(reply)
      expect(buttons(html)).not.toContain('Draft it as an n8n workflow')
      expect(text(html)).not.toContain('safety checker')
    }
  })

  it('sits on the card, so it goes when the card does, as once it is no longer the live one', () => {
    for (const reply of [cardWith(WORDS), partWith(WORDS)]) {
      expect(buttons(draw(reply))).toContain(ANY_BLOCK)
      const gone = render(
        <CardLive.Provider value={false}>
          <Answer reply={reply} typed="x" page={PAGE} />
        </CardLive.Provider>,
      )
      expect(buttons(gone)).not.toContain(ANY_BLOCK)
    }
  })

  it('never shows without words to draft, or for someone who is not an Operator', () => {
    expect(buttons(draw(cantWith(null)))).not.toContain(ANY_BLOCK)
    expect(buttons(draw(partWith(null)))).not.toContain(ANY_BLOCK)
    expect(buttons(draw(cardWith(null)))).not.toContain(ANY_BLOCK)
    expect(buttons(draw(cantWith(WORDS), BOB))).not.toContain(ANY_BLOCK)
  })

  it('shows the drafted workflow card for a draft the Planner started, and the refusal words when it did not', () => {
    const started: PlannerReply = { trace_id: null, answer: 'draft_started', drafted_id: 'dw_01JDRAFTRELEASE', refused: null, parts: [] }
    const html = render(<Answer reply={started} typed="x" page={PAGE} />, { view: ready as DraftedWorkflowView })
    expect(text(html)).toContain('Release check')
    expect(render(<Answer reply={{ ...started, drafted_id: null, refused: 'Only an Operator can draft.' }} typed="x" page={PAGE} />)).toBe('')
  })
})

describe('the set-up approval page', () => {
  it('lets an Approver who may decide approve or decline, with the report’s words', () => {
    const html = render(<SetUpApproval view={bobSetUp as SetUpApprovalView} />)
    expect(text(html)).toContain('Set-up approval, from Carol’s draft')
    expect(text(html)).toContain('Release check')
    expect(text(html)).toContain('Needs your approval')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Approve', 'Decline']))
  })

  it('shows what the workflow reads and writes and who approves each write, in view, and no Explain or More details', () => {
    const view = bobSetUp as SetUpApprovalView
    const html = render(<SetUpApproval view={view} />)
    const shown = text(html)
    expect(shown).toContain('What it reads, writes and posts')
    for (const touch of view.report.touches) expect(shown).toContain(`By “${touch.block}”`)
    expect(shown).toContain('Who approves each write')
    for (const write of view.report.approves) expect(shown).toContain(`“${write.block}” ${write.words}`)
    expect(html, 'both are in view, never behind a disclosure').not.toMatch(/<details/)
    expect(shown).not.toMatch(/More details|\bExplain\b|Step by step/)
  })

  it('shows each setting with where it came from, the key for each write block, a guess marked as guessed, and code’s checks, in view', () => {
    const base = bobSetUp as SetUpApprovalView
    const key: ExplainSetting = { label: [{ text: 'Write key for ', quoted: false }, { text: 'Close it', quoted: true }], value: [{ text: 'GitLab ops', quoted: true }], mark: 'filled', said: 'Chosen by Alice' }
    const guess: ExplainSetting = { label: [{ text: 'The Jira project', quoted: true }], value: [{ text: 'MOCK', quoted: true }], mark: 'guessed', said: 'Guessed, and can be changed' }
    const view: SetUpApprovalView = { ...base, report: { ...base.report, settings: [key, guess] } }
    const html = render(<SetUpApproval view={view} />)
    const shown = text(html)
    expect(shown).toContain('Settings')
    expect(shown, 'the key the write block uses, and who chose it').toContain('Write key for “Close it” “GitLab ops” Chosen by Alice')
    expect(shown).toContain('The Jira project” “MOCK” Guessed, and can be changed')
    expect(html, 'a guess is marked, never shown as given').toMatch(/data-mark="guessed"[^>]*>Guessed, and can be changed</)
    expect(shown).toContain('Safety checks')
    expect(shown).toContain('Fixed for you')
    for (const fixed of base.report.fixed) expect(shown).toContain(fixed.words)
    expect(shown).toContain('Passed')
    for (const passed of base.report.passed) expect(shown).toContain(passed.words)
    expect(html, 'all in view, never behind a disclosure').not.toMatch(/<details/)
    expect(shown.indexOf('Who approves each write')).toBeLessThan(shown.indexOf('Settings'))
    expect(shown.indexOf('Settings')).toBeLessThan(shown.indexOf('Safety checks'))
  })

  it('gives the person who asked for it the reason in place of Approve and Decline', () => {
    const html = render(<SetUpApproval view={carolSetUp as SetUpApprovalView} />)
    expect(text(html)).toContain('You can\'t approve it. You asked for it, changed it, answered its questions or sent it.')
    expect(text(html)).toContain('Waiting for approval')
    expect(buttons(html)).not.toContain('Approve')
    expect(buttons(html)).not.toContain('Decline')
  })

  it('shows the outcome and the set-up once it is decided', () => {
    const base = bobSetUp as SetUpApprovalView
    const done: SetUpApprovalView = { ...base, approval: { ...base.approval, status: 'approved', decided_by: 'Bob' }, you_can_decide: false, set_up: { state: 'set_up', use_case_id: 'uc_01JDRAFTRELEASE', words: null } }
    const html = render(<SetUpApproval view={done} />)
    expect(text(html)).toContain('Approved by Bob.')
    expect(text(html)).toContain('Set up as a draft.')
    expect(buttons(html)).toContain('Open it')
  })
})
