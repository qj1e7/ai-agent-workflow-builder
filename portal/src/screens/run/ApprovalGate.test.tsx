import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import asked from '@contracts/fixtures/approvals/apr_01JB8.alice.asked.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import answered from '@contracts/fixtures/approvals/apr_01JB8.bob.answered.json'
import question from '@contracts/fixtures/approvals/question.asked.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ApprovalView } from '../../api/types'
import { MemoryRouter } from 'react-router'
import { ApprovalGate, DeclineReasons, EXACT_WORDS } from './ApprovalGate'
import { withQuestion } from '../../api/queries'
import { APPROVE, askedWords, declinedNow, declineReasons, decisionFor, foundOf, partyOf, yourPart, type Decision } from './decision'
import { AskBox } from './QuestionThread'
import { ANSWER_HELP, NO_QUESTIONS, NOT_ANSWERED, STILL_WAITING, askHelp, askRefusalWords, sentWords } from './questions'
import { approvalTitle, lockWords, withCurrentNames, proposalTitle, type Party } from './words'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const CAROL: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' }
const DECIDED: ApprovalView = {
  ...BOB,
  you_can_decide: false,
  why_not: 'not_open',
  steps: BOB.steps.map((step) => ({ ...step, status: 'approved', decided_by: 'bob', decided_at: '2026-11-03T02:20:23Z' })),
}

const nameOf = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id
const NOBODY = { ownsIt: false, startedIt: false, retriedIt: false, schedule: false } as const
const STARTER: Party = { ...NOBODY, ownsIt: true, startedIt: true }
const OTHER: Party = NOBODY
const idle: Pick<Decision, 'pending' | 'error' | 'decide'> = { pending: null, error: null, decide: () => undefined }
const REASONS = declineReasons('software_watchlist')

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&amp;', '&').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

function draw(approval: ApprovalView, party: Party | null, decision = idle, found = approval.found, me?: string): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <ApprovalGate
        approval={approval}
        page={{ found, part: yourPart(approval, party, nameOf), askedBy: askedWords(approval, nameOf) }}
        decision={decision}
        reasons={REASONS}
        requester="Alice"
        questions={NO_QUESTIONS}
        me={me}
        nameOf={nameOf}
      />
    </MemoryRouter>,
  )
}

describe('the approval gate', () => {
  it('in the side panel shows everything that will be written and the decision, and leaves Why, Who asked and Your part for the page', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ApprovalGate approval={BOB} page={null} decision={idle} reasons={REASONS} requester="Alice" questions={NO_QUESTIONS} me="bob" nameOf={nameOf} />
      </MemoryRouter>,
    )
    expect(text(html)).toContain('What will change')
    expect(text(html)).toContain(EXACT_WORDS)
    expect(text(html)).toContain('Nothing is written until you say yes.')
    expect(buttons(html)).toEqual(['Approve 1 ticket', 'Decline', 'Ask Alice a question'])
    for (const left of ['Why', 'Who asked', 'Your part']) expect(text(html)).not.toContain(left)
  })

  it('shows bob, an Approver who is not a party to the run, Approve and Decline', () => {
    const html = draw(BOB, OTHER)
    expect(buttons(html)).toEqual(['Approve 1 ticket', 'Decline', 'Ask Alice a question'])
    expect(text(html)).toContain('You can decide because you didn’t set this up or start this run.')
    expect(text(html)).not.toContain('another Approver must decide')
  })

  it('has the five parts the spec names, in order', () => {
    const html = text(draw(BOB, OTHER))
    const at = ['What will change', 'Why', 'Who asked', 'What happens', 'Your part'].map((name) => html.indexOf(name))
    expect(at.every((index) => index >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
  })

  it('says why the agents think so, who asked, and what happens, in plain words', () => {
    const html = text(draw(BOB, OTHER))
    expect(html).toContain('LangGraph has a new release: 1.2.16.')
    expect(html).toContain('Software watchlist, set up by Alice. Alice started this run.')
    expect(html).toContain('Nothing is written until you say yes.')
    expect(html).toContain('The request waits until someone decides. If you decline, the run stops there.')
  })

  it('says it once that nothing is written until a yes, and names no stop time or backup', () => {
    const html = text(draw(BOB, OTHER))
    expect(html.match(/Nothing is written until/g)).toHaveLength(1)
    expect(html).not.toMatch(/backup|expires|stops at|reminder/i)
  })

  it('says that the summary helps the reader and is not the check', () => {
    expect(text(draw(BOB, OTHER))).toContain('What will be written is listed above.')
  })

  it('links a ticket key in the summary only when the proposal writes to that project', () => {
    const html = draw(BOB, OTHER, idle, 'MOCK-12 already covers part of this. GPT-4 is not a ticket.')
    expect(html).toMatch(/<a[^>]*>MOCK-12<\/a>/)
    expect(html).not.toMatch(/<a[^>]*>GPT-4<\/a>/)
  })

  it('reads the summary from the activity once the approval no longer carries it', () => {
    const decided = { ...BOB, found: '' }
    const fromActivity = foundOf('The agents found 1.2.16.', decided.found)
    expect(text(draw(decided, OTHER, idle, fromActivity))).toContain('The agents found 1.2.16.')
    expect(foundOf('', 'From the approval.')).toBe('From the approval.')
    expect(foundOf('', undefined)).toBe('')
    expect(text(draw(decided, OTHER, idle, ''))).toContain('The agents left no summary.')
  })

  it('says who asked by a schedule, and who retried', () => {
    const scheduled: ApprovalView = { ...BOB, trigger: 'schedule', retried_by: ['carol'] }
    expect(askedWords(scheduled, nameOf)).toBe("Software watchlist, set up by Alice. Alice's schedule started this run. Carol retried it.")
  })

  it.each([
    ['alice, who set it up and started the run', ALICE, STARTER, 'You set this workflow up and started this run, so another Approver must decide. Nobody approves their own work.'],
    ['a retrier', { ...ALICE, retried_by: ['dave'] }, { ...OTHER, retriedIt: true }, 'You retried this run, so another Approver must decide. Nobody approves their own work.'],
    ['the owner of a scheduled run', { ...ALICE, trigger: 'schedule' as const }, { ...STARTER, schedule: true }, 'You set up the schedule that started this run, so another Approver must decide. Nobody approves their own work.'],
    ['carol, who is not an Approver', CAROL, OTHER, 'Only an Approver can decide.'],
  ])('shows %s no buttons, and says why', (_who, approval, party, words) => {
    const html = draw(approval, party)
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain(words)
  })

  it('says whose yes came first when this is the second of two', () => {
    const two: ApprovalView = {
      ...BOB,
      steps: [
        { index: 0, label: 'First approver', status: 'approved', decided_by: 'carol', decided_at: '2026-11-03T02:20:23Z' },
        { index: 1, label: 'Second approver', status: 'open', decided_by: null, decided_at: null },
      ],
    }
    expect(yourPart(two, OTHER, nameOf)).toBe('Carol said yes. Your yes is the second of two.')
    expect(text(draw(two, OTHER))).toContain('It needs two Approvers, one after the other.')
  })

  it.each([
    ['bob', BOB],
    ['alice', ALICE],
    ['carol', CAROL],
  ])('shows %s exactly what will be written', (_who, approval) => {
    const html = draw(approval, OTHER)
    const [action] = approval.actions
    expect(text(html)).toContain(approvalTitle(approval.actions))
    expect(text(html)).toContain(String(action?.fields['title']))
    expect(text(html)).toContain(EXACT_WORDS)
  })

  it('names the count and the project in its heading', () => {
    expect(proposalTitle(BOB.actions)).toBe('1 ticket will be created in Jira project MOCK')
    const three = [...BOB.actions, ...BOB.actions, ...BOB.actions]
    expect(proposalTitle(three)).toBe('3 tickets will be created in Jira project MOCK')
  })

  it('names the Jira the tickets go to, before the Approver says yes', () => {
    expect(approvalTitle(BOB.actions)).toBe('1 ticket will be created in Jira project MOCK on the practice Jira')
    expect(text(draw(BOB, OTHER))).toContain('1 ticket will be created in Jira project MOCK on the practice Jira')
    const [action] = BOB.actions
    if (!action) throw new Error('the fixture has one action')
    const real = { ...action, site_name: 'jira.example.com' }
    expect(approvalTitle([real, real])).toBe('2 tickets will be created in Jira project MOCK on jira.example.com')
    const gone = { ...action, site_name: 'a Jira that is no longer set up' }
    expect(approvalTitle([gone])).toBe('1 ticket will be created in Jira project MOCK on a Jira that is no longer set up')
  })

  it('shows neither buttons nor a lock once the step is decided, while the chat catches up', () => {
    const html = draw(DECIDED, OTHER)
    expect(buttons(html)).toEqual([])
    expect(text(html)).not.toContain('already decided')
    expect(text(html)).not.toContain('Your part')
    expect(text(html)).not.toContain('What happens')
  })

  it('keeps focus on the pressed button while the decision is on its way, and holds the other one', () => {
    const html = draw(BOB, OTHER, { ...idle, pending: 'approve' })
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*aria-busy="true"[^>]*>[\s\S]*?Approve 1 ticket/)
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>Decline<\/button>/)
    expect(html).not.toMatch(/<button[^>]*\sdisabled=""/)
  })

  it('says what went wrong as an alert', () => {
    expect(draw(BOB, OTHER, { ...idle, error: 'Another Approver decided this step first.' })).toMatch(/role="alert"[^>]*>Another Approver decided this step first\./)
  })
})

describe('how the person is tied to the run', () => {
  it('reads the owner, the starter and the retriers from the approval', () => {
    expect(partyOf(ALICE, 'alice')).toEqual({ ownsIt: true, startedIt: true, retriedIt: false, schedule: false })
    expect(partyOf({ ...ALICE, retried_by: ['bob'] }, 'bob')).toEqual({ ownsIt: false, startedIt: false, retriedIt: true, schedule: false })
    expect(partyOf(BOB, undefined)).toBeNull()
    expect(partyOf(undefined, 'bob')).toBeNull()
  })
})

describe('what a decision posts', () => {
  it('sends the open step and the digest of the proposal bob is looking at', () => {
    expect(decisionFor(BOB, APPROVE)).toEqual({ step: 0, verdict: 'approve', digest: BOB.digest })
    expect(decisionFor(BOB, { verdict: 'decline', reason: null })).toEqual({ step: 0, verdict: 'decline', digest: BOB.digest })
  })

  it('sends a reason only with a decline, and none when none was picked', () => {
    expect(decisionFor(BOB, { verdict: 'decline', reason: 'Wrong version' })).toEqual({ step: 0, verdict: 'decline', digest: BOB.digest, reason: 'Wrong version' })
    expect(decisionFor(BOB, { verdict: 'decline', reason: null })).not.toHaveProperty('reason')
    expect(decisionFor(BOB, APPROVE)).not.toHaveProperty('reason')
  })

  it('sends nothing for someone the platform says may not decide, or when no step is open', () => {
    expect(decisionFor(ALICE, APPROVE)).toBeNull()
    expect(decisionFor(CAROL, APPROVE)).toBeNull()
    expect(decisionFor({ ...DECIDED, you_can_decide: true }, APPROVE)).toBeNull()
    expect(decisionFor(undefined, APPROVE)).toBeNull()
  })

  it('knows the record of a decline the platform just recorded, with whoever said yes first', () => {
    const at = '2026-11-03T02:20:23Z'
    expect(declinedNow(BOB.steps, { step: 0, by: 'bob', verdict: 'decline', at, reason: 'Wrong version' })).toEqual({ by: 'bob', approvedBy: [], reason: 'Wrong version' })
    const steps: ApprovalView['steps'] = [
      { index: 0, label: 'Team approver', status: 'approved', decided_by: 'bob', decided_at: at, reason: null },
      { index: 1, label: 'Second approver', status: 'open', decided_by: null, decided_at: null, reason: null },
    ]
    expect(declinedNow(steps, { step: 1, by: 'alice', verdict: 'decline', at, reason: null })).toEqual({ by: 'alice', approvedBy: ['bob'], reason: null })
  })
})

describe('declining', () => {
  const reasons = (picked: string | null, pending = false) =>
    renderToStaticMarkup(<DeclineReasons reasons={REASONS} requester="Carol" picked={picked} pending={pending} busy={pending} onPick={() => undefined} onDecline={() => undefined} onBack={() => undefined} />)

  it('asks why, says it is optional and who sees it, and offers the quick reasons, Decline and Back', () => {
    const html = reasons(null)
    expect(text(html)).toMatch(/^Why are you declining\? Optional\. Carol sees it with the record\./)
    expect(buttons(html)).toEqual(['Not this week', 'Wrong version', 'Needs testing first', 'Decline', 'Back'])
    const label = html.match(/role="group" aria-labelledby="([^"]+)"/)?.[1] ?? 'none'
    expect(html).toContain(`<p id="${label}"><b>Why are you declining?</b>`)
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

describe('why someone cannot decide', () => {
  it('names how the person is tied to the run', () => {
    expect(lockWords('own_work', { ...STARTER, schedule: true })).toBe('You set up the schedule that started this run, so another Approver must decide. Nobody approves their own work.')
    expect(lockWords('own_work', { ...OTHER, retriedIt: true })).toBe('You retried this run, so another Approver must decide. Nobody approves their own work.')
    expect(lockWords('own_work', { ...OTHER, ownsIt: true })).toBe('You set this workflow up, so another Approver must decide. Nobody approves their own work.')
    expect(lockWords('own_work', null)).toBe('This run is your own work, so another Approver must decide. Nobody approves their own work.')
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

const ASKED = asked as ApprovalView
const ANSWERED = answered as ApprovalView
const QUESTION = question as ApprovalView['questions'][number]
const decided = (approval: ApprovalView): ApprovalView => ({
  ...approval,
  you_can_decide: false,
  why_not: 'not_open',
  steps: approval.steps.map((step) => ({ ...step, status: 'declined', decided_by: 'bob', decided_at: '2026-11-03T02:20:23Z' })),
})

describe('questions on a request', () => {
  it('offers Bob a quieter Ask under Approve and Decline, and nobody who can’t decide', () => {
    expect(text(draw(BOB, OTHER, idle, BOB.found, 'bob'))).toContain('Not sure yet? Ask Alice a question')
    for (const [approval, party] of [
      [ALICE, STARTER],
      [CAROL, OTHER],
      [DECIDED, OTHER],
    ] as const) {
      expect(text(draw(approval, party))).not.toContain('Ask Alice a question')
    }
  })

  it('opens a box that says Alice sees it and the request stays open, with Send question and Cancel', () => {
    const html = renderToStaticMarkup(<AskBox requester="Alice" ask={NO_QUESTIONS.ask} onSent={() => undefined} onCancel={() => undefined} />)
    expect(text(html)).toContain('Your question for Alice')
    expect(text(html)).toContain(askHelp('Alice'))
    expect(buttons(html)).toEqual(['Send question', 'Cancel'])
  })

  it('shows Bob his question waiting for an answer, and leaves him Approve, Decline and Ask', () => {
    const html = draw({ ...BOB, questions: ASKED.questions }, OTHER, idle, BOB.found, 'bob')
    expect(text(html)).toContain(`Questions You asked Alice: ${QUESTION.text} ${STILL_WAITING}`)
    expect(buttons(html)).toEqual(['Approve 1 ticket', 'Decline', 'Ask Alice a question'])
  })

  it('gives Alice, the requester, an answer box under the question, and still no way to decide', () => {
    const html = draw(ASKED, STARTER, idle, ASKED.found, 'alice')
    expect(text(html)).toContain(`Bob asked you: ${QUESTION.text} Your answer for Bob`)
    expect(text(html)).toContain(ANSWER_HELP)
    expect(buttons(html)).toEqual(['Send answer'])
  })

  it('shows the answer under the question, in the reader’s own words', () => {
    expect(text(draw(ANSWERED, OTHER, idle, ANSWERED.found, 'bob'))).toContain(`You asked Alice: ${QUESTION.text} Alice answered: Yes. We tested it with the team on Friday.`)
    expect(text(draw(ANSWERED, OTHER, idle, ANSWERED.found, 'carol'))).toContain('Bob asked Alice:')
  })

  it.each([
    ['alice', STARTER],
    ['bob', OTHER],
  ])('keeps the questions on the record once it is decided, read only, for %s', (me, party) => {
    const html = draw(decided(ASKED), party, idle, '', me)
    expect(text(html)).toContain(`${QUESTION.text} ${NOT_ANSWERED}`)
    expect(text(html)).not.toContain('Your answer for')
    expect(buttons(html)).toEqual([])
  })

  it('shows the questions in the side panel too', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ApprovalGate approval={{ ...BOB, questions: ASKED.questions }} page={null} decision={idle} reasons={REASONS} requester="Alice" questions={NO_QUESTIONS} me="bob" nameOf={nameOf} />
      </MemoryRouter>,
    )
    expect(text(html)).toContain(`You asked Alice: ${QUESTION.text}`)
  })

  it('says a refused question in its own words, never as a decision', () => {
    const refusals = ['own_work', 'not_an_approver', 'not_open', 'decided_earlier_step', 'not_eligible', 'stale_digest'] as const
    for (const refusal of refusals) expect(askRefusalWords(refusal)).toMatch(/\bask|question/)
    expect(askRefusalWords('own_work')).toBe('This is your own request, so another Approver asks about it.')
  })

  it('confirms a kept question or answer in the prototype’s words', () => {
    expect(sentWords('Carol')).toBe('Sent to Carol. The request is still waiting for a yes.')
  })

  it('puts a sent question or answer in its place before the next read, once', () => {
    const sent = withQuestion(BOB, QUESTION)
    expect(sent.questions).toEqual([QUESTION])
    expect(withQuestion(sent, ANSWERED.questions[0]!).questions).toEqual(ANSWERED.questions)
    expect(sent.steps).toEqual(BOB.steps)
  })
})
