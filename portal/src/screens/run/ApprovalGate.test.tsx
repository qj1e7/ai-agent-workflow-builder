import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ApprovalView } from '../../api/types'
import { ApprovalGate, EXACT_WORDS } from './ApprovalGate'
import { decisionFor, type Decision } from './decision'
import { lockWords, shortLockWords, withCurrentNames, proposalTitle, type Party } from './words'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const CAROL: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' }
const DECIDED: ApprovalView = {
  ...BOB,
  you_can_decide: false,
  why_not: 'not_open',
  steps: BOB.steps.map((step) => ({ ...step, status: 'approved', decided_by: 'bob', decided_at: '2026-11-03T02:20:23Z' })),
}

const STARTER: Party = { startedIt: true, retriedIt: false, schedule: false }
const OTHER: Party = { startedIt: false, retriedIt: false, schedule: false }
const idle: Pick<Decision, 'pending' | 'error' | 'decide'> = { pending: null, error: null, decide: () => undefined }

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&amp;', '&').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

function draw(approval: ApprovalView, party: Party | null, decision = idle): string {
  return renderToStaticMarkup(<ApprovalGate approval={approval} cannotDecide={lockWords(approval.why_not, party)} decision={decision} />)
}

describe('the approval gate', () => {
  it('shows bob, an Approver who is not a party to the run, Approve and Decline', () => {
    const html = draw(BOB, OTHER)
    expect(buttons(html)).toEqual(['Approve 1 ticket', 'Decline'])
    expect(text(html)).not.toContain('can’t approve')
  })

  it.each([
    ['alice, who started the run', ALICE, STARTER, 'You started this run, so you can’t approve it. Nobody approves their own work.'],
    ['carol, who is not an Approver', CAROL, OTHER, 'Only an Approver can decide.'],
  ])('shows %s no buttons, and says why', (_who, approval, party, words) => {
    const html = draw(approval, party)
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain(words)
  })

  it.each([
    ['bob', BOB],
    ['alice', ALICE],
    ['carol', CAROL],
  ])('shows %s exactly what will be written', (_who, approval) => {
    const html = draw(approval, OTHER)
    const [action] = approval.actions
    expect(text(html)).toContain(proposalTitle(approval.actions))
    expect(text(html)).toContain(String(action?.fields['title']))
    expect(text(html)).toContain(EXACT_WORDS)
  })

  it('names the count and the project in its heading', () => {
    expect(proposalTitle(BOB.actions)).toBe('1 ticket will be created in Jira project MOCK')
    const three = [...BOB.actions, ...BOB.actions, ...BOB.actions]
    expect(proposalTitle(three)).toBe('3 tickets will be created in Jira project MOCK')
  })

  it('shows neither buttons nor a lock once the step is decided, while the chat catches up', () => {
    const html = draw(DECIDED, OTHER)
    expect(buttons(html)).toEqual([])
    expect(text(html)).not.toContain('already decided')
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

describe('what a decision posts', () => {
  it('sends the open step and the digest of the proposal bob is looking at', () => {
    expect(decisionFor(BOB, 'approve')).toEqual({ step: 0, verdict: 'approve', digest: BOB.digest })
    expect(decisionFor(BOB, 'decline')).toEqual({ step: 0, verdict: 'decline', digest: BOB.digest })
  })

  it('sends nothing for someone the platform says may not decide, or when no step is open', () => {
    expect(decisionFor(ALICE, 'approve')).toBeNull()
    expect(decisionFor(CAROL, 'approve')).toBeNull()
    expect(decisionFor({ ...DECIDED, you_can_decide: true }, 'approve')).toBeNull()
    expect(decisionFor(undefined, 'approve')).toBeNull()
  })
})

describe('why someone cannot decide', () => {
  it('names how the person is tied to the run', () => {
    expect(lockWords('own_work', { ...STARTER, schedule: true })).toBe('Your schedule started this run, so you can’t approve it. Nobody approves their own work.')
    expect(lockWords('own_work', { ...OTHER, retriedIt: true })).toBe('You retried this run, so you can’t approve it. Nobody approves their own work.')
    expect(lockWords('own_work', OTHER)).toBe('You own this workflow, so you can’t approve its runs. Nobody approves their own work.')
    expect(lockWords('own_work', null)).toBe('This run is your own work, so you can’t approve it. Nobody approves their own work.')
  })

  it('has a short form for the Teams message that never guesses how the person is tied to the run', () => {
    expect(shortLockWords('own_work')).toBe('This run is your own work, so another Approver must decide.')
    expect(shortLockWords('not_an_approver')).toBe('Only an Approver can decide.')
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
