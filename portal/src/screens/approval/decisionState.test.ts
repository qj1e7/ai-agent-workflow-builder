import { describe, expect, it } from 'vitest'
import type { ApprovalStepView, ApprovalView, DecisionOut, DevUser } from '../../api/types'
import { decisionRequest, decisionState, stepBlocks, type DecisionAttempt } from './decisionState'

const DIGEST = 'sha256:0be2129632d1283e015efcae22757aa3e182793e0153503bdd30dc0327a42576'

const alice: DevUser = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const bob: DevUser = { id: 'bob', display: 'Bob', roles: ['approver'] }
const carol: DevUser = { id: 'carol', display: 'Carol', roles: ['operator'] }

function step(index: number, status: ApprovalStepView['status'], by: string | null = null): ApprovalStepView {
  return {
    index,
    label: index === 0 ? 'First approver' : 'Second approver',
    status,
    decided_by: by,
    decided_at: by ? '2026-11-03T02:20:23.447Z' : null,
  }
}

function view(overrides: Partial<ApprovalView>): ApprovalView {
  return {
    approval_id: 'apr_01JB8',
    run_id: 'run_01JB8',
    digest: DIGEST,
    actions: [],
    steps: [step(0, 'open')],
    you_can_decide: true,
    why_not: null,
    ...overrides,
  }
}

const none: DecisionAttempt = { kind: 'none' }

function recorded(decisionStep: number, verdict: 'approve' | 'decline', status: DecisionOut['status']): DecisionAttempt {
  return {
    kind: 'recorded',
    sent: { digest: DIGEST, step: decisionStep, verdict },
    out: { status, decision: { step: decisionStep, by: 'bob', verdict, at: '2026-11-03T02:20:23.447Z' } },
  }
}

describe('what the decision panel offers', () => {
  it('lets Bob decide the open step', () => {
    const state = decisionState(view({}), bob, none)
    expect(state.panel).toEqual({ kind: 'can_decide', step: step(0, 'open') })
    expect(state.notice).toBeNull()
  })

  it('tells Alice, who started the run, that another Approver must decide', () => {
    const state = decisionState(view({ you_can_decide: false, why_not: 'own_work' }), alice, none)
    expect(state.panel).toMatchObject({
      kind: 'cannot_decide',
      words: 'You started this run, so another Approver must decide.',
      hint: 'Send the link to another Approver.',
    })
  })

  it('tells Carol, who is not an Approver, who she is signed in as and where to send the link', () => {
    const state = decisionState(view({ you_can_decide: false, why_not: 'not_an_approver' }), carol, none)
    expect(state.panel).toMatchObject({ kind: 'cannot_decide', words: 'Only Approvers can decide this request.' })
    expect(state.panel.kind === 'cannot_decide' && state.panel.hint).toBe(
      'You are signed in as Carol, who is not an Approver. Send the link to an Approver.',
    )
  })

  it('shows who approved and when once every step is approved', () => {
    const steps = [step(0, 'approved', 'bob')]
    const state = decisionState(view({ steps, you_can_decide: false, why_not: 'not_open' }), bob, none)
    expect(state.panel).toEqual({ kind: 'decided', verdict: 'approve', by: 'bob', at: '2026-11-03T02:20:23.447Z' })
  })

  it('treats a declined step as the end, even when a later step never opened', () => {
    const steps = [step(0, 'declined', 'bob'), step(1, 'waiting')]
    const state = decisionState(view({ steps, you_can_decide: false, why_not: 'not_open' }), alice, none)
    expect(state.panel).toMatchObject({ kind: 'decided', verdict: 'decline', by: 'bob' })
  })

  it('offers the second step to the person who may decide it after the first was approved', () => {
    const steps = [step(0, 'approved', 'bob'), step(1, 'open')]
    const state = decisionState(view({ steps }), alice, none)
    expect(state.panel).toEqual({ kind: 'can_decide', step: step(1, 'open') })
  })
})

describe('after the person decides', () => {
  it('shows the recorded decision straight away, before the page reloads', () => {
    const state = decisionState(view({}), bob, recorded(0, 'approve', 'approved'))
    expect(state.panel).toMatchObject({ kind: 'decided', verdict: 'approve', by: 'bob' })
    expect(state.steps[0]).toMatchObject({ status: 'approved', decided_by: 'bob' })
  })

  it('does not offer the next step to the person who just decided the first', () => {
    const steps = [step(0, 'open'), step(1, 'waiting')]
    const state = decisionState(view({ steps }), bob, recorded(0, 'approve', 'open'))
    expect(state.steps.map((each) => each.status)).toEqual(['approved', 'waiting'])
    expect(state.panel.kind).toBe('cannot_decide')
  })

  it('keeps the panel and shows the server message when the server refuses', () => {
    const attempt: DecisionAttempt = {
      kind: 'refused',
      refusal: { refusal: 'own_work', message: 'You started this run, so another Approver must decide.' },
    }
    const state = decisionState(view({}), bob, attempt)
    expect(state.notice).toEqual({ kind: 'refused', message: 'You started this run, so another Approver must decide.' })
    expect(state.panel.kind).toBe('can_decide')
  })

  it('reports that another Approver got there first, and follows the reloaded view', () => {
    const steps = [step(0, 'approved', 'dana')]
    const state = decisionState(view({ steps, you_can_decide: false, why_not: 'not_open' }), bob, { kind: 'conflict' })
    expect(state.notice).toEqual({ kind: 'conflict' })
    expect(state.panel).toMatchObject({ kind: 'decided', by: 'dana' })
  })
})

describe('the request that is sent', () => {
  it('carries the fingerprint, the open step and the verdict', () => {
    const open = view({ steps: [step(0, 'approved', 'bob'), step(1, 'open')] })
    const { panel } = decisionState(open, alice, none)
    expect(decisionRequest(open, panel, 'decline')).toEqual({ digest: DIGEST, step: 1, verdict: 'decline' })
  })

  it('sends nothing when the person cannot decide', () => {
    const closed = view({ you_can_decide: false, why_not: 'own_work' })
    const { panel } = decisionState(closed, alice, none)
    expect(decisionRequest(closed, panel, 'approve')).toBeNull()
  })
})

describe('the steps list', () => {
  const nameOf = (id: string) => (id === 'bob' ? 'Bob' : id)
  const now = Date.parse('2026-11-03T02:30:00Z')

  it('names who decided each step and when, and shows the open one as waiting', () => {
    const blocks = stepBlocks([step(0, 'approved', 'bob'), step(1, 'open')], nameOf, now)
    expect(blocks[0]).toMatchObject({ name: 'First approver', state: { kind: 'approved', by: 'Bob' } })
    expect(blocks[0]?.description).toMatch(/^Decided at \d\d:\d\d\.$/)
    expect(blocks[1]).toMatchObject({ name: 'Second approver', state: { kind: 'waiting' } })
  })

  it('says a later step opens after the earlier one', () => {
    const [, second] = stepBlocks([step(0, 'open'), step(1, 'waiting')], nameOf, now)
    expect(second?.state.kind).toBe('not_reached')
    expect(second?.description).toBe('Opens after the earlier step is decided.')
  })
})
