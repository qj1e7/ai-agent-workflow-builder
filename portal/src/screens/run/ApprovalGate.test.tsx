import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import asked from '@contracts/fixtures/approvals/apr_01JB8.alice.asked.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import answered from '@contracts/fixtures/approvals/apr_01JB8.bob.answered.json'
import question from '@contracts/fixtures/approvals/question.asked.json'
import registry from '@contracts/fixtures/planner/capabilities.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ApprovalStepView, ApprovalView, CapabilitiesView, CapabilityView } from '../../api/types'
import { MemoryRouter } from 'react-router'
import { ApprovalGate, DeclineReasons, NotChecked, type ApprovalGateProps } from './ApprovalGate'
import { withQuestion } from '../../api/queries'
import { declineReasons, notCheckedWords, partyOf, stepsAfter } from './decision'
import type { LiveRun } from './liveRun'
import { AskBox } from './QuestionThread'
import { ANSWER_HELP, NO_QUESTIONS, NOT_ANSWERED, STILL_WAITING, askRefusalWords, sentWords } from './questions'
import { statusWords } from './RunPage'
import { emptyModel, type Phase } from './runModel'
import { factsOf, lockWords, withCurrentNames, type Party } from './words'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const CAROL: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' }
const AT = '2026-11-03T01:04:00Z'
const NOW = new Date('2026-11-03T10:00:00+08:00')
const decidedAs = (approval: ApprovalView, status: ApprovalStepView['status'], reason: string | null = null): ApprovalView => ({
  ...approval,
  you_can_decide: false,
  why_not: 'not_open',
  steps: approval.steps.map((step) => ({ ...step, status, decided_by: status === 'approved' || status === 'declined' ? 'bob' : null, decided_at: AT, reason })),
})
const TWO: ApprovalView = {
  ...BOB,
  steps: [
    { index: 0, label: 'First approver', status: 'open', decided_by: null, decided_at: null, reason: null, post: 'sent' },
    { index: 1, label: 'Second approver', status: 'waiting', decided_by: null, decided_at: null, reason: null, post: 'sent' },
  ],
}
const SECOND: ApprovalView = {
  ...BOB,
  steps: [
    { index: 0, label: 'First approver', status: 'approved', decided_by: 'carol', decided_at: '2026-11-03T01:01:00Z', reason: null, post: 'sent' },
    { index: 1, label: 'Second approver', status: 'open', decided_by: null, decided_at: null, reason: null, post: 'sent' },
  ],
}

const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id
const NOBODY = { ownsIt: false, startedIt: false, retriedIt: false, schedule: false } as const
const STARTER: Party = { ...NOBODY, ownsIt: true, startedIt: true }
const idle: ApprovalGateProps['decision'] = { pending: null, recorded: null, steps: null, error: null, decide: () => undefined }
const REASONS = declineReasons('software_watchlist')
const TITLE = 'Upgrade LangGraph from 1.2.14 to 1.2.16'

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&amp;', '&').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))
const pill = (html: string) => text(html.match(/<span[^>]*data-approval-pill[^>]*>([\s\S]*?)<\/span>/)?.[1] ?? '')

function draw(approval: ApprovalView, { me = 'bob', decision = idle, notChecked = [], facts = null, next = null }: Partial<Pick<ApprovalGateProps, 'decision' | 'notChecked' | 'facts' | 'next'>> & { me?: string } = {}): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <ApprovalGate
        approval={approval}
        decision={decision}
        facts={facts}
        notChecked={notChecked}
        reasons={REASONS}
        requester="Alice"
        questions={NO_QUESTIONS}
        me={me}
        party={partyOf(approval, me)}
        nameOf={nameOf}
        next={next}
        now={NOW}
      />
    </MemoryRouter>,
  )
}

describe('the approval, waiting for Bob’s yes', () => {
  it('heads it with whose workflow asks, what it will write and a pill that says it needs their yes', () => {
    const html = draw(BOB)
    expect(text(html)).toMatch(/^Approval, from Alice’s Software watchlist Create 1 Jira ticket Needs your yes/)
    expect(pill(html)).toBe('Needs your yes')
  })

  it('shows exactly what will be written, from the request’s own records: where, the summary and the details', () => {
    const html = text(draw(BOB))
    expect(html).toContain(`What will be written Where Jira project MOCK on the practice Jira Summary ${TITLE} Details LangGraph has 2 new releases`)
    expect(html).toContain('Proposed by the AI workflow builder.')
  })

  it('shows every other field the write carries as its own row, so nothing that will be written is hidden', () => {
    const [ticket] = BOB.actions
    if (!ticket) throw new Error('the fixture has one action')
    const fields = { ...ticket.fields, issue_type: 'Task', priority: 'Medium', labels: ['upgrade', 'fastapi'], due: null, story_points: 3 }
    const html = text(draw({ ...BOB, actions: [{ ...ticket, fields }] }))
    expect(html).toContain(`Summary ${TITLE} Details LangGraph has 2 new releases`)
    expect(html).toContain('Proposed by the AI workflow builder. Issue type Task Priority Medium Labels upgrade, fastapi Due None Story points 3')
  })

  it('shows a summary or details the write carries even when they are blank, rather than hide them', () => {
    const [ticket] = BOB.actions
    if (!ticket) throw new Error('the fixture has one action')
    expect(text(draw({ ...BOB, actions: [{ ...ticket, fields: { title: '', body: 'Text' } }] }))).toContain('Summary Empty Details Text')
  })

  it('draws no Fields row when the write carries only its summary and details', () => {
    expect(text(draw(BOB))).not.toMatch(/Fields|Issue type/)
  })

  it('offers Ask Alice, then Approve, then Decline last, with one main button', () => {
    const html = draw(BOB)
    expect(buttons(html)).toEqual(['Ask Alice', 'Approve', 'Decline'])
    expect(html.match(/class="[^"]*primary/g)).toHaveLength(1)
  })

  it('leaves the AI’s summary, Why you and Sent off the request', () => {
    const html = text(draw(BOB))
    for (const gone of ['Summary by AI', 'Why you', 'Sent']) expect(html).not.toContain(gone)
  })

  it('keeps focus on the pressed button while the decision is on its way, and holds the others', () => {
    const html = draw(BOB, { decision: { ...idle, pending: 'approve' } })
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*aria-busy="true"[^>]*>[\s\S]*?Approve/)
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>Decline<\/button>/)
    expect(html).not.toMatch(/<button[^>]*\sdisabled=""/)
  })

  it('says what went wrong as an alert', () => {
    expect(draw(BOB, { decision: { ...idle, error: 'Another Approver decided this step first.' } })).toMatch(/role="alert"[^>]*>Another Approver decided this step first\./)
  })
})

describe('the approval, for someone who can’t say yes', () => {
  it.each([
    ['alice, whose work it is', ALICE, 'alice', 'Waiting for an Approver. You can’t approve your own work.'],
    ['carol, who isn’t an Approver', CAROL, 'carol', 'Waiting for an Approver. Only an Approver can decide.'],
  ])('shows %s the same change, a waiting pill, no buttons, and why', (_who, approval, me, words) => {
    const html = draw(approval, { me })
    expect(pill(html)).toBe('Waiting for a yes')
    expect(text(html)).toContain(TITLE)
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain(words)
  })

})

describe('two Approvers, one after the other', () => {
  it('tells Bob and Alice it is step 1 of 2', () => {
    expect(text(draw(TWO))).toContain('Step 1 of 2. It needs two Approvers, one after the other.')
    expect(text(draw({ ...TWO, you_can_decide: false, why_not: 'own_work' }, { me: 'alice' }))).toContain('Step 1 of 2. It needs two Approvers, one after the other.')
  })

  it('tells the second Approver who approved first', () => {
    const html = text(draw(SECOND))
    expect(html).toContain('Step 2 of 2. Carol approved first.')
    expect(html.match(/Carol approved/g), 'who approved first is said once').toHaveLength(1)
    expect(buttons(draw(SECOND))).toEqual(['Ask Alice', 'Approve', 'Decline'])
  })

  it('never offers the first Approver the second yes: right after it, and once the platform says so', () => {
    const after = stepsAfter(TWO.steps, { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })
    const now = draw(TWO, { decision: { ...idle, recorded: 'approve', steps: after } })
    expect(buttons(now)).toEqual([])
    expect(text(now)).toContain('Step 2 of 2. Bob approved first.')
    expect(text(now)).toContain('Waiting for another Approver. You said yes to the step before, and no one says yes twice.')
    const read = draw({ ...SECOND, steps: [{ ...SECOND.steps[0]!, decided_by: 'bob' }, SECOND.steps[1]!], you_can_decide: false, why_not: 'decided_earlier_step' })
    expect(buttons(read)).toEqual([])
    expect(text(read)).toContain('You said yes to the step before')
  })
})

describe('the record, once it is decided or over', () => {
  it('right after Bob’s yes: approved, and creating the ticket, ahead of the platform’s next read', () => {
    const steps = stepsAfter(BOB.steps, { step: 0, by: 'bob', verdict: 'approve', at: AT, reason: null })
    const html = draw(BOB, { decision: { ...idle, recorded: 'approve', steps }, facts: factsOf('awaiting_approval', { count: 1 }) })
    expect(pill(html)).toBe('Approved')
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain('Approved by Bob at 9:04. Creating the ticket…')
  })

  it('once written: the ticket’s key and a Created stamp', () => {
    const html = draw(decidedAs(BOB, 'approved'), { facts: factsOf('succeeded', { count: 1, refs: ['MOCK-22'] }) })
    expect(text(html)).toContain('Approved by Bob at 9:04. MOCK-22 created.')
    expect(html).toMatch(/<span[^>]*aria-hidden="true"[^>]*>Created<\/span>/)
  })

  it('declined: the reason, nothing written, what happens next, and never created', () => {
    const html = draw(decidedAs(BOB, 'declined', 'Not this week'), { me: 'alice', facts: factsOf('rejected', { declinedBy: 'bob' }), next: 'The tickets will be proposed again at the next check, tomorrow at 8:00.' })
    expect(pill(html)).toBe('Declined')
    expect(text(html)).toContain('Declined by Bob at 9:04: not this week. Nothing was written. The tickets will be proposed again at the next check, tomorrow at 8:00.')
    expect(text(html)).not.toMatch(/created|Created/)
    expect(buttons(html)).toEqual([])
  })

  it.each([
    ['expired', 'No answer', 'No one said yes in time. Nothing was written, and it can’t be decided now.'],
    ['cancelled', 'Cancelled', 'The workflow was deleted before anyone decided. Nothing was written, and it can’t be decided now.'],
    ['closed', 'Closed', 'The platform was updated before anyone decided. Nothing was written, and it can’t be decided now.'],
  ] as const)('%s: says why nobody can decide, even if an old read still says Bob may', (status, label, words) => {
    const html = draw({ ...BOB, steps: BOB.steps.map((step) => ({ ...step, status })) })
    expect(pill(html)).toBe(label)
    expect(text(html)).toContain(words)
    expect(buttons(html)).toEqual([])
  })

  it('keeps what will be written and what wasn’t checked on the record, read only', () => {
    const html = text(draw(decidedAs(BOB, 'declined'), { notChecked: ['Redis couldn’t be read, so no ticket is proposed for it.'] }))
    expect(html).toContain(TITLE)
    expect(html).toContain('Not checked Redis couldn’t be read')
  })
})

describe('what the run didn’t check', () => {
  const CAPABILITIES = (registry as CapabilitiesView).capabilities
  const VERSION_CHECKER = ['crd_version_checker']
  const SUMMARY_CARD = ['crd_weekly_summary']
  /** The registry as the platform serves it once the team has a ticket summary agent: it reads Jira, and nothing else. */
  const withSummary = (capabilities: readonly CapabilityView[]) =>
    capabilities.map((c) => (c.tools.includes('jira.search') ? { ...c, agents: [...c.agents, ...SUMMARY_CARD] } : c))
  const UNREAD = ['Grafana', 'LangServe', 'PostgreSQL', 'Python']
  const SUMMARY_LINES = ['The platform can’t yet see a ticket’s component or priority.', 'The platform can’t yet look past the 50 newest tickets.']
  const SOFTWARE_LINES = ['Grafana, LangServe, PostgreSQL and Python couldn’t be read, so no ticket is proposed for them.', 'The platform can’t yet check PyPI, NuGet or Docker Hub, support end dates, or which vulnerabilities attackers are using.']

  it('names the software a check couldn’t read, then what the registry says the platform can’t check yet', () => {
    expect(notCheckedWords(UNREAD, VERSION_CHECKER, CAPABILITIES)).toEqual(SOFTWARE_LINES)
    expect(notCheckedWords(['Redis'], VERSION_CHECKER, CAPABILITIES)[0]).toBe('Redis couldn’t be read, so no ticket is proposed for it.')
  })

  it('gives a ticket summary what its agents can’t see of a ticket, only as far as the registry says so', () => {
    expect(notCheckedWords([], SUMMARY_CARD, withSummary(CAPABILITIES))).toEqual(SUMMARY_LINES)
    const planned = withSummary(CAPABILITIES).map((c) => (c.id === 'jira.find_by_update' ? { ...c, state: 'planned' as const, cant: 'see when a ticket was last updated, its type or who owns it' } : c))
    expect(notCheckedWords([], SUMMARY_CARD, planned)).toEqual(['The platform can’t yet see when a ticket was last updated, its type or who owns it.', ...SUMMARY_LINES])
  })

  it('writes the registry’s apostrophes the way the Portal writes its own', () => {
    for (const line of notCheckedWords([], SUMMARY_CARD, withSummary(CAPABILITIES))) expect(line).not.toContain("'")
  })

  it('gives a release check the release line, though its agent also reads Jira for the tickets it raised', () => {
    expect(notCheckedWords([], VERSION_CHECKER, CAPABILITIES)).toEqual(['The platform can’t yet check PyPI, NuGet or Docker Hub, support end dates, or which vulnerabilities attackers are using.'])
  })

  it('never lists what the registry says is Ready, and claims nothing while the registry is not in', () => {
    const ready = CAPABILITIES.map((c) => (c.id === 'registries.check' ? { ...c, state: 'ready' as const, cant: null } : c))
    expect(notCheckedWords([], VERSION_CHECKER, ready)).toEqual([])
    expect(notCheckedWords(['Redis'], VERSION_CHECKER, undefined)).toEqual(['Redis couldn’t be read, so no ticket is proposed for it.'])
    expect(notCheckedWords([], [], CAPABILITIES)).toEqual([])
  })

  it('sits right after what will be written, for Bob and Alice, and adds no button', () => {
    for (const [approval, me] of [
      [BOB, 'bob'],
      [ALICE, 'alice'],
    ] as const) {
      const html = draw(approval, { me, notChecked: SOFTWARE_LINES })
      expect(text(html)).toContain(`Proposed by the AI workflow builder. Not checked ${SOFTWARE_LINES.join(' ')}`)
      expect(buttons(html)).toEqual(me === 'bob' ? ['Ask Alice', 'Approve', 'Decline'] : [])
    }
  })

  it('leaves the section out when the run checked everything it could', () => {
    expect(text(draw(BOB))).not.toContain('Not checked')
    expect(renderToStaticMarkup(<NotChecked lines={[]} level={3} />)).toBe('')
  })

  it('stays on the run’s record, read only, as its own section', () => {
    const html = renderToStaticMarkup(<NotChecked lines={SOFTWARE_LINES} level={3} />)
    expect(text(html)).toBe(`Not checked ${SOFTWARE_LINES.join(' ')}`)
    expect(html).toMatch(/<h3[^>]*>Not checked<\/h3>/)
    expect(buttons(html)).toEqual([])
  })
})

describe('how the person is tied to the run', () => {
  it('reads the owner, the starter and the retriers from the approval', () => {
    expect(partyOf(ALICE, 'alice')).toEqual({ ownsIt: true, startedIt: true, retriedIt: false, schedule: false })
    expect(partyOf({ ...ALICE, retried_by: ['bob'] }, 'bob')).toEqual({ ownsIt: false, startedIt: false, retriedIt: true, schedule: false })
    expect(partyOf(BOB, undefined)).toBeNull()
    expect(partyOf(undefined, 'bob')).toBeNull()
  })

  it('names how the person is tied to the run when it says why not them', () => {
    expect(lockWords('own_work', { ...STARTER, schedule: true })).toBe('You set up the schedule that started this run, so another Approver must decide. Nobody approves their own work.')
    expect(lockWords('own_work', { ...NOBODY, retriedIt: true })).toBe('You retried this run, so another Approver must decide. Nobody approves their own work.')
    expect(lockWords('own_work', null)).toBe('This run is your own work, so another Approver must decide. Nobody approves their own work.')
  })
})

describe('declining', () => {
  const reasons = (picked: string | null, pending = false) =>
    renderToStaticMarkup(<DeclineReasons reasons={REASONS} requester="Alice" picked={picked} pending={pending} busy={pending} onPick={() => undefined} onDecline={() => undefined} onBack={() => undefined} />)

  it('asks why, says it is optional and that Alice will see it, and offers the quick reasons, Back and Decline last', () => {
    const html = reasons(null)
    expect(text(html)).toMatch(/^Why\? Optional\. Alice will see it\./)
    expect(buttons(html)).toEqual(['Not this week', 'Wrong version', 'Needs testing first', 'Back', 'Decline'])
    const label = html.match(/role="group" aria-labelledby="([^"]+)"/)?.[1] ?? 'none'
    expect(html).toContain(`<p id="${label}"><b>Why?</b>`)
    expect(html.match(/aria-pressed="false"/g)).toHaveLength(3)
  })

  it('marks the one reason picked, with words and not colour alone', () => {
    const html = reasons('Wrong version')
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
    expect(html).toMatch(/aria-pressed="true"[^>]*>[\s\S]*?Wrong version<\/button>/)
  })

  it('holds Back while the decline is on its way', () => {
    const html = reasons('Wrong version', true)
    expect(html).toMatch(/<button[^>]*aria-busy="true"[^>]*>[\s\S]*?Decline<\/button>/)
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>Back<\/button>/)
  })

  it('offers the software check its own reasons, and any other workflow two of its own', () => {
    expect(declineReasons('software_watchlist')).toEqual(['Not this week', 'Wrong version', 'Needs testing first'])
    expect(declineReasons('agents')).toEqual(['Not needed this time', 'Something in it is wrong'])
    expect(declineReasons(undefined)).toEqual(['Not needed this time', 'Something in it is wrong'])
  })

  it('names the requester the platform gives as the one who sees the reason', () => {
    expect(BOB.requester).toBe(BOB.started_by)
  })
})

describe('the troubleshooter’s words', () => {
  it('use the names the app uses today', () => {
    expect(withCurrentNames('The use case names a repository that does not exist. Check the token in the use case.')).toBe(
      'The workflow names a repository that does not exist. Check the token in the workflow.',
    )
    expect(withCurrentNames('The template has no connector binding. Ask a maintainer to add the binding to the template.')).toBe(
      'The workflow has no connector binding. Ask a maintainer to add the binding to the workflow.',
    )
    expect(withCurrentNames('The agents proposed an action this use case cannot carry out.')).toBe('The agents proposed an action this workflow cannot carry out.')
    expect(withCurrentNames('the room lead and the Release checker')).toBe('the Planner and the Version checker')
    expect(withCurrentNames('An agent could not finish its work.')).toBe('An agent could not finish its work.')
  })
})

describe('right after this person decides, before the run’s own events say so', () => {
  const liveAt = (phase: Phase): LiveRun => {
    const model = { ...emptyModel, phase }
    return { shown: model, head: model, connection: { is: 'live' }, loadedUpTo: 0, loaded: true }
  }
  it('says nothing of an approval on the page while the run’s own events catch up, since the record and the pill already say it', () => {
    expect(statusWords(liveAt({ state: 'acting' }))).toBe('')
  })

  it('still shows the question thread to the person who decided', () => {
    const steps = stepsAfter(BOB.steps, { step: 0, by: 'bob', verdict: 'decline', at: AT, reason: null })
    const bobDecided = text(draw({ ...BOB, questions: ASKED.questions }, { decision: { ...idle, recorded: 'decline', steps } }))
    expect(bobDecided).toContain('Has 1.2.16 been tested with our login service?')
    expect(bobDecided).not.toContain('Ask Alice')
  })
})

const ASKED = asked as ApprovalView
const ANSWERED = answered as ApprovalView
const QUESTION = question as ApprovalView['questions'][number]

describe('questions on a request', () => {
  it('offers Ask Alice to Bob, and to nobody who can’t decide', () => {
    expect(buttons(draw(BOB))).toContain('Ask Alice')
    for (const [approval, me] of [
      [ALICE, 'alice'],
      [CAROL, 'carol'],
      [decidedAs(BOB, 'approved'), 'bob'],
    ] as const) {
      expect(buttons(draw(approval, { me }))).not.toContain('Ask Alice')
    }
  })

  it('opens a box named Ask Alice a question, with Back and Send', () => {
    const html = renderToStaticMarkup(<AskBox requester="Alice" ask={NO_QUESTIONS.ask} onSent={() => undefined} onCancel={() => undefined} />)
    expect(html).toMatch(/<label[^>]*>Ask Alice a question<\/label>/)
    expect(buttons(html)).toEqual(['Back', 'Send'])
  })

  it('shows Bob their question and that the request stays open, and leaves them Ask, Approve and Decline', () => {
    const html = draw({ ...BOB, questions: ASKED.questions })
    expect(text(html)).toContain(`You asked Alice: ${QUESTION.text} ${STILL_WAITING}`)
    expect(STILL_WAITING).toBe('No reply yet. The request stays open.')
    expect(buttons(html)).toEqual(['Ask Alice', 'Approve', 'Decline'])
  })

  it('gives Alice, the requester, an answer box under the question, and still no way to decide', () => {
    const html = draw(ASKED, { me: 'alice' })
    expect(text(html)).toContain(`Bob asked you: ${QUESTION.text} Your answer for Bob`)
    expect(text(html)).toContain(ANSWER_HELP)
    expect(buttons(html)).toEqual(['Send answer'])
  })

  it('shows the answer under the question, in the reader’s own words', () => {
    expect(text(draw(ANSWERED))).toContain(`You asked Alice: ${QUESTION.text} Alice answered: Yes. We tested it with the team on Friday.`)
    expect(text(draw(ANSWERED, { me: 'carol' }))).toContain('Bob asked Alice:')
  })

  it.each(['alice', 'bob'])('keeps the questions on the record once it is decided, read only, for %s', (me) => {
    const html = draw(decidedAs(ASKED, 'declined'), { me })
    expect(text(html)).toContain(`${QUESTION.text} ${NOT_ANSWERED}`)
    expect(text(html)).not.toContain('Your answer for')
    expect(buttons(html)).toEqual([])
  })

  it('says a refused question in its own words, never as a decision', () => {
    const refusals = ['own_work', 'not_an_approver', 'not_open', 'decided_earlier_step', 'not_eligible', 'stale_digest'] as const
    for (const refusal of refusals) expect(askRefusalWords(refusal)).toMatch(/\bask|question/)
    expect(askRefusalWords('own_work')).toBe('This is your own request, so another Approver asks about it.')
  })

  it('confirms a kept question or answer in the prototype’s words', () => {
    expect(sentWords('Carol')).toBe('Sent to Carol. The request is still waiting for approval.')
  })

  it('puts a sent question or answer in its place before the next read, once', () => {
    const sent = withQuestion(BOB, QUESTION)
    expect(sent.questions).toEqual([QUESTION])
    expect(withQuestion(sent, ANSWERED.questions[0]!).questions).toEqual(ANSWERED.questions)
    expect(sent.steps).toEqual(BOB.steps)
  })
})
