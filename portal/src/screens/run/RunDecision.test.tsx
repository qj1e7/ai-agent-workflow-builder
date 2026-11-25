import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { ApprovalStepView, ApprovalView } from '../../api/types'
import { declineReasons, partyOf, stepsAfter } from './decision'
import { RunDecision, type RunDecisionProps } from './RunDecision'
import { NO_QUESTIONS } from './questions'
import { factsOf } from './words'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const AT = '2026-11-03T01:04:00Z'
const NOW = new Date('2026-11-03T10:00:00+08:00')
const FOUND = 'LangGraph 1.2.16 is out (2 Nov).'
const BODY = 'LangGraph has 2 new releases on GitHub (langchain-ai/langgraph) newer than our version 1.2.14:\n- 1.2.16\n- 1.2.15\n\nProposed by the AI workflow builder.'

const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id
const idle: RunDecisionProps['decision'] = { pending: null, recorded: null, steps: null, error: null, decide: () => undefined }
const decidedAs = (approval: ApprovalView, status: ApprovalStepView['status'], reason: string | null = null): ApprovalView => ({
  ...approval,
  you_can_decide: false,
  why_not: 'not_open',
  steps: approval.steps.map((step) => ({ ...step, status, decided_by: 'bob', decided_at: AT, reason })),
})

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&amp;', '&').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

function draw(approval: ApprovalView, over: Partial<RunDecisionProps> & { me?: string } = {}): string {
  const { me = 'bob', ...rest } = over
  return renderToStaticMarkup(
    <MemoryRouter>
      <RunDecision
        approval={approval}
        found={FOUND}
        tense="wants"
        decision={idle}
        facts={null}
        reasons={declineReasons('software_watchlist')}
        requester="Alice"
        questions={NO_QUESTIONS}
        me={me}
        party={partyOf(approval, me)}
        nameOf={nameOf}
        next={null}
        now={NOW}
        {...rest}
      />
    </MemoryRouter>,
  )
}

describe('the run page’s decision, for an Approver while it waits', () => {
  const html = draw(BOB)

  it('leads with what was found, then what the run wants to do, then the ticket as a small preview', () => {
    const words = text(html)
    expect(words.indexOf(FOUND)).toBe(0)
    expect(words.indexOf('This run wants to create 1 Jira ticket in MOCK:')).toBeGreaterThan(words.indexOf(FOUND))
    expect(words.indexOf('Upgrade LangGraph from 1.2.14 to 1.2.16')).toBeGreaterThan(words.indexOf('This run wants'))
    expect(words).toContain('LangGraph has 2 new releases on GitHub (langchain-ai/langgraph) newer than our version 1.2.14:')
  })

  it('says who decides and when they were asked', () => {
    expect(text(html)).toContain('An Approver decides in Teams (asked 10:14).')
  })

  it('offers Ask Alice, Approve and Decline in the same block, with one main button', () => {
    expect(buttons(html)).toEqual(['Ask Alice', 'Approve', 'Decline'])
    expect(html.match(/class="[^"]*primary/g)).toHaveLength(1)
  })

  it('opens the whole ticket, exactly as it will be written, behind Show full text', () => {
    expect(html).toMatch(/<details[^>]*>[\s\S]*Show full text[\s\S]*<\/details>/)
    const full = text(html)
    expect(full).toContain('Where Jira project MOCK on the practice Jira Summary Upgrade LangGraph from 1.2.14 to 1.2.16 Details')
    expect(full).toContain(BODY.replace(/\s+/g, ' '))
  })

  it('shows every other field the write carries when the full text is open, so nothing that will be written is hidden', () => {
    const [ticket] = BOB.actions
    if (!ticket) throw new Error('the fixture has one action')
    const fields = { ...ticket.fields, issue_type: 'Task', labels: ['upgrade', 'fastapi'] }
    expect(text(draw({ ...BOB, actions: [{ ...ticket, fields }] }))).toContain('Issue type Task Labels upgrade, fastapi')
  })

  it('leaves out what the page no longer carries: the AI’s summary, Not checked, the old rows and the status', () => {
    const words = text(html)
    for (const gone of ['Summary by AI', 'Not checked', 'What will be written', 'Why you', 'Why not you', 'Sent', 'Waiting for approval', 'Needs your']) expect(words).not.toContain(gone)
    expect(html).not.toContain('data-run-pill')
    expect(html).not.toContain('data-approval-pill')
  })

  it('never says yes as a noun', () => {
    expect(text(html)).not.toMatch(/\byes\b/i)
  })
})

describe('the same decision for the person who started the run', () => {
  const html = draw(ALICE, { me: 'alice' })

  it('says they cannot approve their own run, and offers no way to', () => {
    expect(text(html)).toContain('An Approver decides in Teams (asked 10:14). You can’t approve your own run.')
    expect(buttons(html)).toEqual([])
  })

  it('still shows the found line and the whole ticket', () => {
    expect(text(html)).toContain(FOUND)
    expect(text(html)).toContain('Upgrade LangGraph from 1.2.14 to 1.2.16')
    expect(html).toContain('Show full text')
  })
})

describe('someone who is not an Approver', () => {
  it('reads why they cannot decide, and has no buttons', () => {
    const html = draw({ ...BOB, you_can_decide: false, why_not: 'not_an_approver' }, { me: 'carol' })
    expect(text(html)).toContain('Only an Approver can decide.')
    expect(buttons(html)).toEqual([])
  })
})

describe('two Approvers, one after the other', () => {
  const TWO: ApprovalView = {
    ...BOB,
    steps: [
      { index: 0, label: 'First approver', status: 'approved', decided_by: 'carol', decided_at: '2026-11-03T01:01:00Z', reason: null, post: 'sent' },
      { index: 1, label: 'Second approver', status: 'open', decided_by: null, decided_at: null, reason: null, post: 'sent', sent_at: '2026-11-03T01:02:00Z' },
    ],
  }

  it('says whose turn it is, and who approved first, without yes', () => {
    const words = text(draw(TWO))
    expect(words).toContain('Step 2 of 2. Carol approved first.')
    expect(words).not.toMatch(/\byes\b/i)
    expect(buttons(draw(TWO))).toEqual(['Ask Alice', 'Approve', 'Decline'])
  })

  it('offers the first Approver nothing more once their approval is recorded here', () => {
    const open: ApprovalView = { ...TWO, steps: [{ ...TWO.steps[0]!, status: 'open', decided_by: null }, { ...TWO.steps[1]!, status: 'waiting' }] }
    const steps = stepsAfter(open.steps, { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })
    const html = draw(open, { decision: { ...idle, recorded: 'approve', steps } })
    expect(buttons(html)).toEqual([])
  })
})

describe('the same structure once the request is decided', () => {
  it('right after approval: who approved, and that the ticket is being created, with the wants line in the present', () => {
    const steps = stepsAfter(BOB.steps, { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })
    const html = draw(BOB, { tense: 'doing', decision: { ...idle, recorded: 'approve', steps }, facts: factsOf('awaiting_approval', { count: 1 }) })
    expect(text(html)).toContain('This run is creating 1 Jira ticket in MOCK:')
    expect(text(html)).toContain('Approved by Bob at 9:04. Creating the ticket…')
    expect(buttons(html)).toEqual([])
  })

  it('once written: the ticket’s key and a Created stamp, with the wants line in the past', () => {
    const html = draw(decidedAs(BOB, 'approved'), { tense: 'did', facts: factsOf('succeeded', { count: 1, refs: ['MOCK-22'] }) })
    expect(text(html)).toContain('This run created 1 Jira ticket in MOCK:')
    expect(text(html)).toContain('Approved by Bob at 9:04. MOCK-22 created.')
    expect(html).toMatch(/<span[^>]*aria-hidden="true"[^>]*>Created<\/span>/)
  })

  it('declined: who declined and why, that nothing was written, and what happens next, and never created', () => {
    const html = draw(decidedAs(BOB, 'declined', 'Not this week'), {
      me: 'alice',
      tense: 'wanted',
      facts: factsOf('rejected', { declinedBy: 'bob' }),
      next: 'The tickets will be proposed again at the next check, tomorrow at 8:00.',
    })
    expect(text(html)).toContain('This run wanted to create 1 Jira ticket in MOCK:')
    expect(text(html)).toContain('Declined by Bob at 9:04: not this week. Nothing was written. The tickets will be proposed again at the next check, tomorrow at 8:00.')
    expect(text(html)).not.toMatch(/\bcreated\b|Created/)
    expect(buttons(html)).toEqual([])
  })

  it('leaves out the found line when the run has none', () => {
    expect(text(draw(BOB, { found: null })).startsWith('This run wants to create')).toBe(true)
  })
})
