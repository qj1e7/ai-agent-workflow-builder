import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import rowsAnswer from '../../../../contracts/fixtures/builder/understand.rows.json'
import watchlist from '../../../../contracts/fixtures/builder/understand.watchlist.json'
import useCase from '../../../../contracts/fixtures/builder/use-case.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { DraftView, Me, PlanOut, UnderstandOut, UseCaseView } from '../../api/types'
import { DoneRoute } from './DonePage'
import { afterReading, changeRow, draftContent, EMPTY_FORM, enterWhen, taskWithoutSchedule, planView, type Form } from './draft'
import { NewWorkflowRoute } from './NewWorkflow'
import { StepCheck, type PlanState } from './StepCheck'
import { StepReview } from './StepReview'
import { StepWhen } from './StepWhen'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const NOW = new Date('2026-11-03T15:00:00+08:00')
const FOLLOW_UP = 'Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
const DRAFTED: PlanOut = {
  decision: 'new_agent',
  draft: {
    name: 'Stale bug follow-up',
    purpose: 'Lists stale bug tickets in one new ticket.',
    good_for: [],
    inputs: [{ name: 'Jira project', kind: 'jira_project', what: 'Where to look and write.', example: 'ABC' }],
    blocks: [
      { say: 'Find bug tickets with no update for 10 days.', tool: 'jira.search' },
      { say: 'Propose one ticket that lists them.', tool: 'jira.create_ticket' },
    ],
    approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
  },
  approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
  problems: [],
  reason: 'No saved agent does this.',
  missing_tools: [],
  questions: [],
}

function wrap(node: ReactNode, { me = ALICE, path = '/new', seed }: { me?: Me; path?: string; seed?: (client: QueryClient, scope: string) => void } = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  queryClient.setQueryData(['me', scope], me)
  seed?.(queryClient, scope)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/new" element={node} />
            <Route path="/new/done/:useCaseId" element={node} />
          </Routes>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&quot;', '"').replace(/\s+/g, ' ').trim()
const heading = (html: string) => text(/<h1\b[^>]*>([\s\S]*?)<\/h1>/.exec(html)?.[1] ?? '')
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const buttonTag = (html: string, name: string) => [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find((m) => text(m[2] ?? '') === name)?.[1] ?? ''
const read = (answer: UnderstandOut, words = FOLLOW_UP): Form => afterReading({ ...EMPTY_FORM, text: words }, answer)
const noop = () => undefined
const planState = (view: PlanState['view'], pending = false): PlanState => ({ view, pending, error: null, retry: noop })

function check(form: Form, plan: PlanState): string {
  return wrap(<StepCheck form={form} plan={plan} onChangeRow={noop} onDropRow={noop} onValue={noop} onBack={noop} onNext={noop} onCarryOn={noop} />)
}

describe('New workflow for an Operator', () => {
  const html = wrap(<NewWorkflowRoute />)

  it('says it is step 1 of 4 in its heading, and marks the step', () => {
    expect(heading(html)).toBe('New workflow , step 1 of 4: Describe it')
    expect(html).toMatch(/<h1 tabindex="-1">/)
    expect(text(/<li[^>]*aria-current="step"[^>]*>([\s\S]*?)<\/li>/.exec(html)?.[1] ?? '')).toBe('1. Describe it')
  })

  it('asks what should happen, offers three starters, Plan it and Save draft and close', () => {
    expect(html).toContain('<label for="task">What should happen?</label>')
    expect(buttons(html)).toEqual(['Save draft and close', 'Follow up stale bug tickets', 'Weekly summary of closed tickets', 'Check Kubernetes releases', 'Plan it'])
    expect(text(html)).toContain('Tell me what you want done.')
  })
})

describe('New workflow for an Approver who is not an Operator', () => {
  it('says only Operators set up workflows, and offers no form', () => {
    const html = wrap(<NewWorkflowRoute />, { me: BOB })
    expect(heading(html)).toBe('New workflow')
    expect(text(html)).toContain('Only Operators set up workflows. Ask an Operator on your team.')
    expect(html).not.toContain('textarea')
  })
})

describe('a draft opened from Home', () => {
  it('reopens at the step it was saved at', () => {
    const form = { ...enterWhen(read(rowsAnswer as UnderstandOut)), step: 3 as const }
    const draft: DraftView = {
      draft_id: 'd1',
      step: 3,
      content: JSON.parse(JSON.stringify(draftContent(form, { task: taskWithoutSchedule(form.rows), answer: DRAFTED }))) as DraftView['content'],
      created_at: '2026-11-03T07:00:00Z',
      saved_at: '2026-11-03T07:00:00Z',
    }
    const html = wrap(<NewWorkflowRoute />, { path: '/new?draft=d1', seed: (client, scope) => client.setQueryData(['drafts', scope], [draft]) })
    expect(heading(html)).toBe('New workflow , step 3 of 4: When it runs')
    expect(html).toMatch(/<option value="weekdays" selected="">Every weekday<\/option>/)
    expect(html).toContain('value="15:00"')
  })
})

describe('step 2', () => {
  it('shows each part the Planner understood, the plan with what writes, and the Jira project it found', () => {
    const form = read(rowsAnswer as UnderstandOut)
    const html = check(form, planState(planView(DRAFTED, form.rows)))
    expect(text(html)).toContain('Your words ' + FOLLOW_UP)
    expect(text(html)).toContain('When Every weekday at 3pm , from your words')
    expect(text(html)).toContain('Where it goes Jira project MOCK , from your words')
    expect(text(html)).toContain('Propose one ticket that lists them. Changes data, waits for a yes')
    expect(text(html)).toContain('Stale bug follow-up is a new agent.')
    expect(html).toMatch(/<input id="value-0-jira-project" type="text"[^>]*value="MOCK"/)
    expect(buttonTag(html, 'Next')).not.toContain('aria-disabled')
  })

  it('keeps Next off at a missing schedule and a part it can’t do, and says why', () => {
    const teams = read(
      {
        answer: 'rows',
        rows: [
          { kind: 'schedule', text: '', state: 'missing', note: 'You didn’t say when it runs.' },
          { kind: 'look_for', text: 'Tickets with no update for 14 days', state: 'changed', note: 'You said “stale”, so I used 14 days without an update.' },
          { kind: 'do', text: 'Write a short summary', state: 'understood', note: null },
          { kind: 'where', text: 'Post it in Teams', state: 'cant_do', note: 'I can’t post in Teams yet.' },
        ],
      },
      'Post a summary of stale tickets in Teams',
    )
    const html = check(teams, planState(null))
    expect(buttonTag(html, 'Next')).toContain('aria-disabled="true"')
    expect(buttonTag(html, 'Next')).toContain('aria-describedby="next-why"')
    expect(text(html)).toContain('Next opens when you say when it runs and you change what I can’t do.')
    expect(text(html)).toContain('When Not said , please fill in Fill in You didn’t say when it runs.')
    expect(text(html)).toContain('Where it goes Post it in Teams , can’t do this yet Change I can’t post in Teams yet.')
    expect(text(html)).toContain('I’ll plan the steps once every part is clear.')
  })

  it('shows a fixed row as changed by you, with what the request said', () => {
    const form = changeRow(read(rowsAnswer as UnderstandOut), 1, 'Bug tickets in MOCK with no update for 14 days')
    expect(text(check(form, planState(null, true)))).toContain(
      'Looks for Bug tickets in MOCK with no update for 14 days , changed by you Change Your request said: “Bug tickets in MOCK with no update for 10 days”.',
    )
  })

  it('sends a release task to the Software watchlist, and offers to carry on as a new workflow', () => {
    const html = check(read(watchlist as UnderstandOut, 'Tell me when LangGraph has a new release'), planState(null))
    expect(text(html)).toContain('You mentioned “release”')
    expect(html).toMatch(/<a [^>]*href="\/software"[^>]*>Open Software watchlist<\/a>/)
    expect(buttons(html)).toEqual(['Back', 'No, set it up as a new workflow'])
  })
})

describe('step 3', () => {
  it('fills in the schedule from the request’s words', () => {
    const when = enterWhen(read(rowsAnswer as UnderstandOut)).when
    const html = wrap(<StepWhen when={when} asked="Every weekday at 3pm" problems={{}} onWhen={noop} onBack={noop} onNext={noop} />)
    expect(text(html)).toContain('Filled in from your words: Every weekday at 3pm.')
    expect(html).not.toContain('id="when-day"')
  })

  it('says when the request didn’t say when, and points at each missing field', () => {
    const html = wrap(
      <StepWhen
        when={{ often: 'week', day: '', at: '', filledFrom: '' }}
        asked=""
        problems={{ day: 'Choose a day.', at: 'Choose a time.' }}
        onWhen={noop}
        onBack={noop}
        onNext={noop}
      />,
    )
    expect(text(html)).toContain('Your request didn’t say when, so nothing is filled in.')
    expect(html).toMatch(/<select id="when-day"[^>]*aria-invalid="true"[^>]*aria-describedby="when-day-error"/)
    expect(text(html)).toContain('Choose a time.')
  })
})

describe('step 4', () => {
  it('says any Approver but the person setting it up says yes, and checks it against the request', () => {
    const form = { ...enterWhen(read(rowsAnswer as UnderstandOut)), step: 4 as const, name: 'Stale bug follow-up' }
    const html = wrap(<StepReview form={form} plan={planView(DRAFTED, form.rows)} nameProblem={null} busy={false} problems={[]} onName={noop} onBack={noop} onTurnOn={noop} />)
    expect(text(html)).toContain('Every weekday at 15:00 Singapore time, the agents find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them .')
    expect(text(html)).toContain('Who says yes Any Approver except you, in Teams. Nobody approves their own work.')
    expect(text(html)).toContain('When: Every weekday at 15:00, as you asked.')
    expect(buttons(html)).toEqual(['Back', 'Turn it on'])
  })
})

describe('the done page', () => {
  it('says the workflow is on, when it runs next, and offers a test run', () => {
    const view = useCase as UseCaseView
    const html = wrap(<DoneRoute now={NOW} />, {
      path: `/new/done/${view.use_case_id}`,
      seed: (client, scope) => client.setQueryData(['use-case', scope, view.use_case_id], view),
    })
    expect(heading(html)).toBe('Your workflow is on')
    expect(text(html)).toContain(`${view.name} runs next on Mon 9 Nov, 9:00 , Singapore time. When it needs a yes, an Approver gets a message in Teams.`)
    expect(buttons(html)).toContain('Do a test run now')
    expect(html).toMatch(/<a [^>]*href="\/"[^>]*>Back to Home<\/a>/)
  })
})
