import alice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
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
import { BADGE_MAX_ASKS, BADGE_POLL_MS, badgeAsks, badgeText, DrawerHead, MessageBody, teamsLabel, TeamsDecide, TEAMS_TITLE, withSetUps } from './TeamsPanel'
import { wrapTabIn } from '../ui/sidePanel'

const BOB = bob as ApprovalView
const ALICE_APPROVAL = alice as ApprovalView
const idle = { pending: null, recorded: null, steps: null, error: null, decide: () => undefined } as const
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

describe('the badge with set-up approvals', () => {
  it('adds the set-up approvals this person may decide to the approvals waiting for them', () => {
    expect(withSetUps({ count: 2, atLeast: false }, 1)).toEqual({ count: 3, atLeast: false })
    expect(withSetUps({ count: 0, atLeast: false }, 2)).toEqual({ count: 2, atLeast: false })
    expect(badgeText(withSetUps({ count: 0, atLeast: false }, 1))).toBe('1')
    expect(teamsLabel(withSetUps({ count: 1, atLeast: false }, 1))).toBe('Teams, practice copy, 2 approvals waiting for you')
  })

  it('keeps counting “or more” when the runs were cut at the most it asks about', () => {
    expect(withSetUps({ count: BADGE_MAX_ASKS, atLeast: true }, 1)).toEqual({ count: BADGE_MAX_ASKS + 1, atLeast: true })
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
    // Carol started all ten. Alice retried the nine newest, so they are Alice's own work, though Alice did not start them.
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

describe('the practice Teams drawer', () => {
  const buttonsOf = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

  it('has a Close button with the word Close on it, still named Close Teams', () => {
    const html = renderToStaticMarkup(<DrawerHead note="Practice copy." onClose={() => undefined} />)
    expect(buttonsOf(html)).toEqual(['Close'])
    expect(html).toContain('aria-label="Close Teams"')
  })

  it('gives an Approver who may decide Approve, the one primary button, and Decline', () => {
    const html = renderToStaticMarkup(<TeamsDecide approval={BOB} decision={idle} />)
    expect(buttonsOf(html)).toEqual(['Approve', 'Decline'])
    expect(html.match(/_primary_/g)).toHaveLength(1)
  })

  it('gives the person who started the run, and anyone else who may not decide, no Approve or Decline', () => {
    expect(renderToStaticMarkup(<TeamsDecide approval={ALICE_APPROVAL} decision={idle} />)).toBe('')
    expect(renderToStaticMarkup(<TeamsDecide approval={{ ...BOB, you_can_decide: false, why_not: 'not_an_approver' }} decision={idle} />)).toBe('')
    expect(renderToStaticMarkup(<TeamsDecide approval={undefined} decision={idle} />)).toBe('')
  })

  it('offers nothing more once this person’s decision is recorded, and says what was recorded', () => {
    const html = renderToStaticMarkup(<TeamsDecide approval={BOB} decision={{ ...idle, recorded: 'approve' }} />)
    expect(buttonsOf(html)).toEqual([])
    expect(text(html)).toBe('You approved this.')
    expect(text(renderToStaticMarkup(<TeamsDecide approval={BOB} decision={{ ...idle, recorded: 'decline' }} />))).toBe('You declined this.')
  })

  it('shows the platform’s refusal, so a press that fails is never silent', () => {
    const html = renderToStaticMarkup(<TeamsDecide approval={BOB} decision={{ ...idle, error: 'Someone changed this request. Read it again.' }} />)
    expect(html).toContain('role="alert"')
    expect(text(html)).toContain('Someone changed this request. Read it again.')
  })

  it('keeps saying why when the read after a conflict hides the buttons', () => {
    const decided = { ...BOB, you_can_decide: false, why_not: 'not_an_approver' } as ApprovalView
    const html = renderToStaticMarkup(<TeamsDecide approval={decided} decision={{ ...idle, error: 'Another Approver decided this step first.' }} />)
    expect(buttonsOf(html)).toEqual([])
    expect(html).toContain('role="alert"')
    expect(text(html)).toBe('Another Approver decided this step first.')
  })
})

describe('Tab in the open Teams drawer', () => {
  /** A stop the drawer shows, or one it hides, which Tab skips. */
  function stop(name: string, shown = true) {
    return { name, focus: vi.fn(), getClientRects: () => ({ length: shown ? 1 : 0 }) }
  }
  type Stop = ReturnType<typeof stop>
  const drawer = (stops: readonly Stop[]) => ({ querySelectorAll: () => stops }) as unknown as Pick<ParentNode, 'querySelectorAll'>
  function press(stops: readonly Stop[], active: Stop, key = 'Tab', shiftKey = false): { stayed: boolean; focused: string[] } {
    for (const each of stops) each.focus.mockClear()
    const preventDefault = vi.fn()
    wrapTabIn(drawer(stops), active, { key, shiftKey, preventDefault })
    return { stayed: preventDefault.mock.calls.length > 0, focused: stops.filter((each) => each.focus.mock.calls.length > 0).map((each) => each.name) }
  }

  it('keeps focus on Close when Close is all an empty drawer holds, for Tab and Shift+Tab', () => {
    const close = stop('Close')
    expect(press([close], close)).toEqual({ stayed: true, focused: ['Close'] })
    expect(press([close], close, 'Tab', true)).toEqual({ stayed: true, focused: ['Close'] })
  })

  it('goes from the last stop back to Close, and from Close back to the last, and moves as usual between', () => {
    const [close, open, approve] = [stop('Close'), stop('Open in AI Workflow Builder'), stop('Approve')]
    const stops = [close, open, approve]
    expect(press(stops, approve)).toEqual({ stayed: true, focused: ['Close'] })
    expect(press(stops, close, 'Tab', true)).toEqual({ stayed: true, focused: ['Approve'] })
    expect(press(stops, close)).toEqual({ stayed: false, focused: [] })
  })

  it('skips a stop it does not show, and leaves every other key alone', () => {
    const [close, hidden] = [stop('Close'), stop('Hidden', false)]
    expect(press([close, hidden], close)).toEqual({ stayed: true, focused: ['Close'] })
    expect(press([close], close, 'Escape')).toEqual({ stayed: false, focused: [] })
  })
})
