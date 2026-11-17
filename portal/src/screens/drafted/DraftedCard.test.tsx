import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import drafting from '../../../../contracts/fixtures/builder/drafted.drafting.json'
import notDrafted from '../../../../contracts/fixtures/builder/drafted.not-drafted.json'
import question from '../../../../contracts/fixtures/builder/drafted.question.json'
import ready from '../../../../contracts/fixtures/builder/drafted.ready.json'
import setUp from '../../../../contracts/fixtures/builder/drafted.set-up.json'
import waiting from '../../../../contracts/fixtures/builder/drafted.waiting.json'
import bobSetUp from '../../../../contracts/fixtures/builder/setup-approval.bob.json'
import carolSetUp from '../../../../contracts/fixtures/builder/setup-approval.carol.json'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import { ApiProvider } from '../../api/context'
import { draftedKey } from '../../api/draftedQueries'
import { createDevSession } from '../../api/session'
import type { CantReply, DraftedWorkflowView, Me, PartReply, PlannerReply, SetUpApprovalView } from '../../api/types'
import { Answer, type Page } from '../home/AnswerCards'
import { ChatProvider } from '../home/ChatProvider'
import { DraftedCard } from './DraftedCard'
import { SetUpApproval } from './SetUpApprovalPage'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const WORDS = 'Draft an n8n workflow that every Monday at 9:00 checks langchain-ai/langgraph for a new release and raises a ticket in MOCK'
const scope = createDevSession(null).cacheScope()
const BOB: Me = { id: 'u_bob', display: 'Bob', roles: ['approver'] }

function render(node: React.ReactNode, { me, view }: { me?: Me; view?: DraftedWorkflowView } = {}): string {
  const queryClient = new QueryClient()
  if (me) queryClient.setQueryData(['me', scope], me)
  if (view) queryClient.setQueryData(draftedKey(scope, view.drafted_id), view)
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

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const card = (view: DraftedWorkflowView, revision = view.revision) => render(<DraftedCard draftedId={view.drafted_id} revision={revision} />, { view })

describe('the drafted workflow card', () => {
  it('shows Drafting with time going while the drafter works, and no steps the platform did not report', () => {
    const html = card(drafting as DraftedWorkflowView)
    expect(text(html)).toContain('Drafting it as an n8n workflow')
    expect(text(html)).toContain('Revision 1 Drafting')
    expect(html).not.toContain('aria-label="Steps"')
    expect(buttons(html)).toEqual([])
  })

  it('shows a draft with its steps, In short, what was added, and Send for approval, leaving Start from the Portal out', () => {
    const html = card(ready as DraftedWorkflowView)
    const words = text(html)
    expect(words).toContain('Release check')
    expect(words).toContain('Revision 1 Draft')
    expect(words).toContain('Every Monday')
    expect(words).not.toContain('Start from the Portal')
    expect(html).toContain('data-in-short')
    expect(words).toMatch(/Added \d+ things? every workflow needs\./)
    expect(buttons(html)).toEqual(['See the report', 'Ask for a change', 'Send for approval'])
  })

  it('puts the reason where Send for approval would be when it cannot be sent, never a dead button', () => {
    const html = card(question as DraftedWorkflowView)
    expect(text(html)).toContain('Answer 1 question first')
    expect(text(html)).toContain('1 flag. See them')
    expect(buttons(html)).toEqual(['See them', 'See the report', 'Ask for a change'])
    expect(html).not.toContain('disabled')
  })

  it('says it is waiting for an Approver, and cannot be approved by its author', () => {
    const html = card(waiting as DraftedWorkflowView)
    expect(text(html)).toContain('Revision 1 Waiting for a yes')
    expect(text(html)).toContain('Waiting for an Approver. You can’t approve your own draft.')
    expect(buttons(html)).toEqual(['See the report'])
  })

  it('says who approved it and that it is set up as a draft, with Open it', () => {
    const html = card(setUp as DraftedWorkflowView)
    expect(text(html)).toContain('Approved by Bob.')
    expect(text(html)).toContain('Set up as a draft.')
    expect(buttons(html)).toEqual(['See the report', 'Open it'])
    expect(html).toContain('href="/workflows/uc_01JDRAFTRELEASE"')
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
    expect(text(html)).toContain('Revision 1 Declined')
    expect(text(html)).toContain('Declined by Bob: wrong project or channel. Nothing was set up.')
  })

  it('says a new revision cancelled the waiting approval', () => {
    expect(text(card({ ...(ready as DraftedWorkflowView), replaced_waiting: true }))).toContain('This revision cancelled the waiting approval.')
  })

  it('settles an older revision into one line', () => {
    const html = card({ ...(ready as DraftedWorkflowView), revision: 2 }, 1)
    expect(text(html)).toContain('Revision 1. Revision 2 is below.')
    expect(buttons(html)).toEqual([])
  })

  it('says why it was not drafted, with Ask the team', () => {
    const html = card(notDrafted as DraftedWorkflowView)
    expect(text(html)).toContain('I couldn\'t draft that.')
    expect(buttons(html)).toEqual(['Ask the team'])
  })
})

describe('Draft it as an n8n workflow', () => {
  const cantWith = (words: string | null): CantReply => ({ ...(cant as CantReply), draft_words: words })
  const partWith = (words: string | null): PartReply => ({ ...(part as PartReply), draft_words: words })
  const draw = (reply: PlannerReply, me?: Me) => render(<Answer reply={reply} typed="x" page={PAGE} />, me ? { me } : {})

  it('shows for an Operator on a can’t answer and on a part card that carry words to draft', () => {
    expect(buttons(draw(cantWith(WORDS)))).toContain('Draft it as an n8n workflow')
    expect(buttons(draw(partWith(WORDS)))).toContain('Draft it as an n8n workflow')
  })

  it('never shows without words to draft, or for someone who is not an Operator', () => {
    expect(buttons(draw(cantWith(null)))).not.toContain('Draft it as an n8n workflow')
    expect(buttons(draw(partWith(null)))).not.toContain('Draft it as an n8n workflow')
    expect(buttons(draw(cantWith(WORDS), BOB))).not.toContain('Draft it as an n8n workflow')
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
    expect(text(html)).toContain('Needs your yes')
    expect(text(html)).toContain('What it reads, writes and posts')
    expect(text(html)).toContain('More details')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Approve', 'Decline']))
  })

  it('gives the person who asked for it the reason in place of Approve and Decline', () => {
    const html = render(<SetUpApproval view={carolSetUp as SetUpApprovalView} />)
    expect(text(html)).toContain('You can\'t approve it. You asked for it, changed it or sent it.')
    expect(text(html)).toContain('Waiting for a yes')
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
