import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { ApprovalView } from '../api/types'
import type { Decision } from '../screens/run/decision'
import type { Party } from '../screens/run/words'
import { teamsActionOf, TeamsActions, teamsLabel, TEAMS_TITLE, type TeamsAction } from './TeamsPanel'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const CAROL: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' }
const STARTER: Party = { startedIt: true, retriedIt: false, schedule: false }
const names: Record<string, string> = { alice: 'Alice', bob: 'Bob' }
const nameOf = (id: string) => names[id] ?? id

function decided(status: 'approved' | 'declined'): ApprovalView {
  return {
    ...BOB,
    you_can_decide: false,
    why_not: 'not_open',
    steps: BOB.steps.map((step) => ({ ...step, status, decided_by: 'bob', decided_at: '2026-11-03T02:20:23Z' })),
  }
}

const idle: Pick<Decision, 'pending' | 'error' | 'decide'> = { pending: null, error: null, decide: () => undefined }
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

function draw(action: TeamsAction): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <TeamsActions action={action} link="/approvals/apr_01JB8" decision={idle} onOpen={() => undefined} />
    </MemoryRouter>,
  )
}

describe('a Teams message', () => {
  it('offers bob Approve, Decline and Open in Workflow Builder', () => {
    const action = teamsActionOf(BOB, null, nameOf)
    expect(action).toEqual({ kind: 'decide' })
    const html = draw(action)
    expect([...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))).toEqual(['Approve', 'Decline'])
    expect(html).toMatch(/<a\b[^>]*href="\/approvals\/apr_01JB8"[^>]*>Open in Workflow Builder<\/a>/)
  })

  it.each([
    ['alice, who started the run', ALICE, STARTER, 'You started this run, so you can’t approve it.'],
    ['carol, who is not an Approver', CAROL, null, 'Only an Approver can decide.'],
  ])('shows %s a lock line and no buttons', (_who, approval, party, words) => {
    const action = teamsActionOf(approval, party, nameOf)
    expect(action).toEqual({ kind: 'locked', words })
    const html = draw(action)
    expect(html).not.toContain('<button')
    expect(text(html)).toBe(words)
  })

  it.each([
    ['approved', 'Approved by Bob'],
    ['declined', 'Declined by Bob'],
  ] as const)('once %s, says who decided, for everyone', (status, words) => {
    for (const viewer of [decided(status), { ...decided(status), why_not: 'own_work' as const }]) {
      const action = teamsActionOf(viewer, STARTER, nameOf)
      expect(text(draw(action))).toBe(words)
      expect(draw(action)).not.toContain('<button')
    }
  })

  it('shows nothing until the platform has answered for this person', () => {
    expect(draw(teamsActionOf(undefined, null, nameOf))).toBe('')
  })
})

describe('the Teams button', () => {
  it('says how many approvals wait for the signed-in person', () => {
    expect(teamsLabel(0)).toBe(TEAMS_TITLE)
    expect(teamsLabel(1)).toBe('Teams, practice copy, 1 approval waiting for you')
    expect(teamsLabel(3)).toBe('Teams, practice copy, 3 approvals waiting for you')
  })
})
