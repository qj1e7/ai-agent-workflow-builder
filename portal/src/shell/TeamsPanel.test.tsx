import bob from '@contracts/fixtures/approvals/apr_01JB8.bob.json'
import teams from '@contracts/fixtures/stubs/teams-messages.json'
import decidedTeams from '@contracts/fixtures/stubs/teams-messages.decided.json'
import waiting from '@contracts/fixtures/views/success.awaiting_approval.json'
import { environmentManager, QueriesObserver, QueryClient } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../api/client'
import { approvalQuery } from '../api/queries'
import { authorizedFetch, createDevSession } from '../api/session'
import type { ApprovalView, RunView, RunViewOf, TeamsStubMessage } from '../api/types'
import { BADGE_MAX_ASKS, BADGE_POLL_MS, badgeAsks, badgeText, MessageBody, teamsLabel, TEAMS_TITLE } from './TeamsPanel'

const BOB = bob as ApprovalView
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [m[1], text(m[2] ?? '')])

function draw(message: TeamsStubMessage): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <MessageBody message={message} onOpen={() => undefined} />
    </MemoryRouter>,
  )
}

describe('a Teams message', () => {
  it('shows the card a real Teams channel gets, with no Approve or Decline button', () => {
    for (const message of [teams.messages[0], decidedTeams.messages[0]] as TeamsStubMessage[]) {
      const html = draw(message)
      expect(html).not.toContain('<button')
      expect(text(html)).not.toMatch(/\b(Approve|Decline)\b/)
      expect(links(html)).toEqual([['http://localhost:8080/approvals/apr_01JB8', 'Open in AI Workflow Builder']])
    }
  })

  it('shows who decided only once the platform has put it on the card', () => {
    expect(text(draw(teams.messages[0] as TeamsStubMessage))).not.toContain('Approved by')
    expect(text(draw(decidedTeams.messages[0] as TeamsStubMessage))).toMatch(/^Approved by Bob /)
  })

  it('shows a message posted before cards as its words and a link to the approval page', () => {
    const old: TeamsStubMessage = { ...(teams.messages[0] as TeamsStubMessage), card: null, text: 'A run needs an Approver.' }
    const html = draw(old)
    expect(html).not.toContain('<button')
    expect(text(html)).toBe('A run needs an Approver. Open in AI Workflow Builder')
    expect(links(html)).toEqual([['/approvals/apr_01JB8', 'Open in AI Workflow Builder']])
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
