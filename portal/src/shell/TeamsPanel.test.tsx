import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import teams from '@contracts/fixtures/stubs/teams-messages.json'
import waiting from '@contracts/fixtures/views/success.awaiting_approval.json'
import { environmentManager, QueriesObserver, QueryClient } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../api/client'
import { approvalQuery } from '../api/queries'
import { authorizedFetch, createDevSession } from '../api/session'
import type { ApprovalView, RunView, RunViewOf, TeamsStubMessage } from '../api/types'
import type { Decision } from '../screens/run/decision'
import { BADGE_MAX_ASKS, BADGE_POLL_MS, badgeAsks, badgeText, teamsActionOf, TeamsActions, teamsLabel, TEAMS_TITLE, type TeamsAction } from './TeamsPanel'

const BOB = bob as ApprovalView
const ALICE = alice as ApprovalView
const CAROL: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' }
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
const OPEN_LINK = /<a\b[^>]*href="\/approvals\/apr_01JB8"[^>]*>Open in AI Workflow Builder<\/a>/
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

function draw(action: TeamsAction): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <TeamsActions action={action} link="/approvals/apr_01JB8" decision={idle} onOpen={() => undefined} />
    </MemoryRouter>,
  )
}

describe('a Teams message', () => {
  it('offers bob Approve, Decline and Open in AI Workflow Builder', () => {
    const action = teamsActionOf(BOB, nameOf)
    expect(action).toEqual({ kind: 'decide' })
    const html = draw(action)
    expect([...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))).toEqual(['Approve', 'Decline'])
    expect(html).toMatch(OPEN_LINK)
  })

  it.each([
    ['still loading', undefined],
    ['open to decide', BOB],
    ['locked', ALICE],
    ['already decided', decided('approved')],
  ] as const)('links to the run page when %s', (_state, approval) => {
    expect(draw(teamsActionOf(approval, nameOf))).toMatch(OPEN_LINK)
  })

  it.each([
    ['alice, who started the run', ALICE, 'This run is your own work, so another Approver must decide.'],
    ['carol, who is not an Approver', CAROL, 'Only an Approver can decide.'],
  ])('shows %s a lock line and no buttons', (_who, approval, words) => {
    const action = teamsActionOf(approval, nameOf)
    expect(action).toEqual({ kind: 'locked', words })
    const html = draw(action)
    expect(html).not.toContain('<button')
    expect(text(html)).toBe(`${words} Open in AI Workflow Builder`)
  })

  it.each([
    ['approved', 'Approved by Bob'],
    ['declined', 'Declined by Bob'],
  ] as const)('once %s, says who decided, for everyone', (status, words) => {
    for (const viewer of [decided(status), { ...decided(status), why_not: 'own_work' as const }]) {
      const action = teamsActionOf(viewer, nameOf)
      expect(text(draw(action))).toBe(`${words} Open in AI Workflow Builder`)
      expect(draw(action)).not.toContain('<button')
    }
  })

  it('shows only the link until the platform has answered for this person', () => {
    expect(text(draw(teamsActionOf(undefined, nameOf)))).toBe('Open in AI Workflow Builder')
  })

  it('tells anyone tied to the run that it is their own work, without guessing how', () => {
    const retrier: ApprovalView = { ...BOB, you_can_decide: false, why_not: 'own_work' }
    expect(teamsActionOf(retrier, nameOf)).toEqual({ kind: 'locked', words: 'This run is your own work, so another Approver must decide.' })
  })
})

describe('the Teams button', () => {
  it('says how many approvals wait for the signed-in person', () => {
    expect(teamsLabel({ count: 0, atLeast: false })).toBe(TEAMS_TITLE)
    expect(teamsLabel({ count: 1, atLeast: false })).toBe('Teams, practice copy, 1 approval waiting for you')
    expect(teamsLabel({ count: 3, atLeast: false })).toBe('Teams, practice copy, 3 approvals waiting for you')
    expect(teamsLabel({ count: BADGE_MAX_ASKS, atLeast: true })).toBe(`Teams, practice copy, ${BADGE_MAX_ASKS} or more approvals waiting for you`)
  })

  it('shows a count, or the most it counts with a plus', () => {
    expect(badgeText({ count: 0, atLeast: false })).toBeNull()
    expect(badgeText({ count: 3, atLeast: false })).toBe('3')
    expect(badgeText({ count: BADGE_MAX_ASKS, atLeast: true })).toBe(`${BADGE_MAX_ASKS}+`)
  })
})

const WAITING = waiting as RunViewOf<'awaiting_approval'>
const MESSAGE = teams.messages[0] as TeamsStubMessage

function manyWaiting(n: number, startedBy: string, youCanDecide = true): { runs: RunView[]; messages: TeamsStubMessage[] } {
  const runs = Array.from({ length: n }, (_, i) => ({
    ...WAITING,
    run_id: `run_${i}`,
    started_by: startedBy,
    you_can_decide: youCanDecide,
    started_at: new Date(Date.UTC(2026, 10, 3, 2, i)).toISOString(),
    approval: { ...WAITING.approval, approval_id: `apr_${i}`, link: `/approvals/apr_${i}` },
  }))
  const messages = runs.map((run, i) => ({ ...MESSAGE, id: `tm_${i}`, run_id: run.run_id, approval_id: `apr_${i}`, link: `/approvals/apr_${i}` }))
  return { runs, messages }
}

describe('what the badge asks the platform', () => {
  const onServer = environmentManager.isServer()
  afterEach(() => {
    vi.useRealTimers()
    environmentManager.setIsServer(() => onServer)
  })

  it('asks about the newest waiting runs with a Teams message, and no more than it shows', () => {
    const { runs, messages } = manyWaiting(40, 'carol')
    const asks = badgeAsks(runs, messages.slice(1))
    expect(asks.ids).toEqual(Array.from({ length: BADGE_MAX_ASKS }, (_, i) => `apr_${39 - i}`))
    expect(asks.more).toBe(true)
    expect(badgeAsks(runs.slice(0, 3), messages)).toEqual({ ids: ['apr_2', 'apr_1', 'apr_0'], more: false })
  })

  it('skips the runs the platform says this person cannot decide', () => {
    const { runs, messages } = manyWaiting(40, 'alice', false)
    expect(badgeAsks(runs, messages)).toEqual({ ids: [], more: false })
  })

  it('still asks about an older run this person can decide when nine of their own come first', () => {
    // Carol started all ten. Alice retried the nine newest, so they are her own work, though she did not start them.
    const { runs, messages } = manyWaiting(10, 'carol')
    const retried = runs.map((run, i) => (i === 0 ? run : { ...run, you_can_decide: false }))
    expect(badgeAsks(retried, messages)).toEqual({ ids: ['apr_0'], more: false })
  })

  it('sends the same small number of approval requests on every poll, however many runs wait', async () => {
    vi.useFakeTimers()
    // Vitest runs without a window, where TanStack Query never polls. A browser tab polls.
    environmentManager.setIsServer(() => false)
    const { runs, messages } = manyWaiting(200, 'carol')
    const asked: string[] = []
    const fetchImpl: typeof fetch = (input) => {
      const id = new URL(input instanceof Request ? input.url : String(input)).pathname.split('/').at(-1) ?? ''
      asked.push(id)
      return Promise.resolve(new Response(JSON.stringify({ ...BOB, approval_id: id }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }
    const client = createApiClient(authorizedFetch(createDevSession(null), fetchImpl, 'http://portal.test'), 'http://portal.test')
    const queryClient = new QueryClient()
    const asks = badgeAsks(runs, messages)
    const observer = new QueriesObserver(queryClient, asks.ids.map((id) => approvalQuery(client, 'bob', id, { poll: BADGE_POLL_MS })))
    const stop = observer.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    const perPoll = [asked.length]
    for (let poll = 0; poll < 3; poll += 1) {
      const before = asked.length
      await vi.advanceTimersByTimeAsync(BADGE_POLL_MS)
      perPoll.push(asked.length - before)
    }
    stop()
    expect(perPoll).toEqual([BADGE_MAX_ASKS, BADGE_MAX_ASKS, BADGE_MAX_ASKS, BADGE_MAX_ASKS])
    expect(BADGE_POLL_MS).toBeGreaterThanOrEqual(30_000)
  })
})
