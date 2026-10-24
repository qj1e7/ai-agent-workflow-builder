import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApprovalView, MockJiraTicket, RunView, TeamsStubMessage, WatchlistOut, WatchlistView } from '../api/types'
import { createDemoPlatform, type DemoPlatformHandle } from './index'
import { nextStart } from './watchlist'

// Friday 27 Nov 2026, 10:14 in Singapore: the recorded check also started on a Friday at 10:14.
const START = Date.parse('2026-11-27T02:14:00Z')
const ORIGIN = 'http://portal.test/api/v1'
const SECOND = 1000
const WATCHLIST = 'uc_01JBW'

let demo: DemoPlatformHandle

beforeEach(() => {
  vi.useFakeTimers({ now: START })
  demo = createDemoPlatform(START)
})

afterEach(() => {
  vi.useRealTimers()
})

async function call(method: string, path: string, user = 'alice', body?: unknown): Promise<Response> {
  const headers = new Headers({ 'X-Dev-User': user, 'Idempotency-Key': crypto.randomUUID() })
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  return demo.fetch(`${ORIGIN}${path}`, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
}

async function watchlist(user = 'alice'): Promise<WatchlistView> {
  const out = (await (await call('GET', '/watchlist', user)).json()) as WatchlistOut
  if (!out.watchlist) throw new Error('no watchlist')
  return out.watchlist
}

function rows(view: WatchlistView): [string, string][] {
  return view.software.map((row) => [row.name, row.status])
}

function row(view: WatchlistView, name: string) {
  const found = view.software.find((candidate) => candidate.name === name)
  if (!found) throw new Error(`no ${name}`)
  return found
}

async function checkNow(): Promise<string> {
  const response = await call('POST', `/use-cases/${WATCHLIST}/runs`)
  expect(response.status).toBe(201)
  return ((await response.json()) as { run_id: string }).run_id
}

async function untilWaiting(runId: string): Promise<ApprovalView> {
  for (let waited = 0; waited < 120; waited += 1) {
    await vi.advanceTimersByTimeAsync(SECOND)
    const run = (await (await call('GET', `/runs/${runId}`)).json()) as RunView
    if (run.state === 'awaiting_approval') {
      return (await (await call('GET', `/approvals/${run.approval.approval_id}`, 'bob')).json()) as ApprovalView
    }
  }
  throw new Error('the check never waited for an Approver')
}

async function decide(approval: ApprovalView, verdict: 'approve' | 'decline'): Promise<void> {
  const response = await call('POST', `/approvals/${approval.approval_id}/decisions`, 'bob', {
    step: 0,
    verdict,
    digest: approval.digest,
  })
  expect(response.status).toBe(201)
  await vi.advanceTimersByTimeAsync(20 * SECOND)
}

describe('the demo watchlist', () => {
  it('starts as the recorded watchlist, attention first, with Alice checking every Monday at 9:00', async () => {
    const view = await watchlist('bob')
    expect(rows(view)).toEqual([
      ['FastAPI', 'cant_check'],
      ['LangGraph', 'behind'],
      ['Terraform', 'not_checked'],
      ['n8n', 'up_to_date'],
      ['PostgreSQL', 'up_to_date'],
      ['Redis', 'up_to_date'],
    ])
    expect(row(view, 'FastAPI').problem).toBe('GitHub answered 404 Not Found.')
    expect(row(view, 'n8n').our_version_source).toMatchObject({ kind: 'ticket_done', ticket: 'MOCK-140' })
    expect(view.schedule).toMatchObject({ day: 'monday', at: '09:00', owner: 'alice', owner_name: 'Alice' })
    expect(view.schedule?.next_at, 'the next Monday at 9:00 in Singapore').toBe('2026-11-30T01:00:00.000Z')
    expect(view.last_check).toBeNull()
  })

  it('is a use case of the watchlist template, so its runs draw the right line', async () => {
    const { use_cases: useCases } = (await (await call('GET', '/use-cases')).json()) as {
      use_cases: { use_case_id: string; template: string }[]
    }
    expect(useCases.find((useCase) => useCase.use_case_id === WATCHLIST)?.template).toBe('software_watchlist')
  })

  it('lets an Operator add software, and refuses a repository it already watches or cannot read', async () => {
    const added = await call('POST', '/watchlist/software', 'carol', {
      name: 'Grafana',
      repo: 'grafana/grafana',
      our_version: null,
    })
    expect(added.status).toBe(201)
    const view = (await added.json()) as WatchlistView
    expect(row(view, 'Grafana')).toMatchObject({ status: 'not_checked', our_version: null, added_by: 'carol' })
    expect(view.version).toBe(7)

    expect(
      (await call('POST', '/watchlist/software', 'alice', { name: 'Again', repo: 'Grafana/Grafana' })).status,
    ).toBe(409)
    const bad = await call('POST', '/watchlist/software', 'alice', { name: '', repo: 'grafana', our_version: 'v1' })
    expect(bad.status).toBe(422)
    const { detail } = (await bad.json()) as { detail: { loc: string[] }[] }
    expect(detail.map((problem) => problem.loc.at(-1))).toEqual(['name', 'repo', 'our_version'])
    expect(
      (await call('POST', '/watchlist/software', 'bob', { name: 'Grafana', repo: 'grafana/loki' })).status,
      'Bob is an Approver only',
    ).toBe(403)
  })

  it('lets an Operator remove software', async () => {
    const fastapi = row(await watchlist(), 'FastAPI')
    const removed = await call('DELETE', `/watchlist/software/${fastapi.id}`)
    expect(removed.status).toBe(200)
    expect(rows((await removed.json()) as WatchlistView).map(([name]) => name)).not.toContain('FastAPI')
    expect((await call('DELETE', `/watchlist/software/${fastapi.id}`)).status).toBe(404)
  })

  it('makes the person who saves the schedule its owner, and can turn it off', async () => {
    const saved = await call('PUT', '/watchlist/schedule', 'carol', { day: 'every_day', at: '06:30' })
    expect(((await saved.json()) as WatchlistView).schedule).toMatchObject({
      day: 'every_day',
      at: '06:30',
      owner: 'carol',
      owner_name: 'Carol',
    })
    expect(
      (await call('PUT', '/watchlist/schedule', 'carol', { day: 'monday', at: '06:31' })).status,
      'a 5-minute step',
    ).toBe(422)
    expect((await call('PUT', '/watchlist/schedule', 'bob', { day: 'monday', at: '09:00' })).status).toBe(403)
    const off = await call('DELETE', '/watchlist/schedule', 'carol')
    expect(((await off.json()) as WatchlistView).schedule).toBeNull()
  })

  it('refuses to check an empty watchlist', async () => {
    for (const software of (await watchlist()).software) await call('DELETE', `/watchlist/software/${software.id}`)
    const response = await call('POST', `/use-cases/${WATCHLIST}/runs`)
    expect(response.status).toBe(409)
  })
})

describe('a check in the demo', () => {
  it('replays the recorded check, and its three tickets wait for one decision', async () => {
    const runId = await checkNow()
    const approval = await untilWaiting(runId)
    expect(approval.actions.map((action) => action.fields['title'])).toEqual([
      'Upgrade LangGraph from 1.2.14 to 1.2.16',
      'Upgrade Redis from 8.2.0 to 8.2.1',
      'Upgrade PostgreSQL from 17.2.0 to 17.3.0',
    ])
    const view = await watchlist()
    expect(rows(view)).toEqual([
      ['FastAPI', 'cant_check'],
      ['LangGraph', 'awaiting_approval'],
      ['PostgreSQL', 'awaiting_approval'],
      ['Redis', 'awaiting_approval'],
      ['n8n', 'up_to_date'],
      ['Terraform', 'up_to_date'],
    ])
    expect(row(view, 'Redis').approval_id).toBe(approval.approval_id)
    expect(row(view, 'Terraform')).toMatchObject({ our_version: '1.9.8', our_version_source: { kind: 'first_check' } })
    expect(view.last_check).toMatchObject({ run_id: runId, state: 'awaiting_approval' })

    await vi.advanceTimersByTimeAsync(5 * SECOND)
    const { messages } = (await (await call('GET', '/teams-stub/messages')).json()) as { messages: TeamsStubMessage[] }
    expect(messages.find((message) => message.run_id === runId)?.text).toBe(
      'A run of Software watchlist needs an Approver. It would create 3 Jira tickets in MOCK: "Upgrade LangGraph from 1.2.14 to 1.2.16", "Upgrade Redis from 8.2.0 to 8.2.1" and "Upgrade PostgreSQL from 17.2.0 to 17.3.0". Open the approval page to decide. The agents said: 3 of 6 watched software have new releases: LangGraph 1.2.16, Redis 8.2.1 and PostgreSQL 17.3.0. FastAPI could not be checked.',
    )
  })

  it('writes the tickets on approval, and Mark Done moves our version', async () => {
    const runId = await checkNow()
    await decide(await untilWaiting(runId), 'approve')
    const { tickets } = (await (await call('GET', '/mock-jira/tickets')).json()) as { tickets: MockJiraTicket[] }
    const written = tickets.filter((ticket) => ticket.run_id === runId)
    expect(
      written.map((ticket) => [ticket.title, ticket.status]),
      'newest first',
    ).toEqual([
      ['Upgrade PostgreSQL from 17.2.0 to 17.3.0', 'To Do'],
      ['Upgrade Redis from 8.2.0 to 8.2.1', 'To Do'],
      ['Upgrade LangGraph from 1.2.14 to 1.2.16', 'To Do'],
    ])
    const redis = row(await watchlist(), 'Redis')
    expect(redis.status).toBe('ticket_open')
    const key = redis.open_ticket ?? ''
    expect(written.find((ticket) => ticket.key === key)?.title).toBe('Upgrade Redis from 8.2.0 to 8.2.1')

    expect(
      (await call('POST', `/mock-jira/tickets/${key}/done`, 'bob')).status,
      'only an Operator marks a ticket Done',
    ).toBe(403)
    const done = await call('POST', `/mock-jira/tickets/${key}/done`)
    expect(((await done.json()) as MockJiraTicket).status).toBe('Done')
    expect((await call('POST', `/mock-jira/tickets/${key}/done`)).status, 'marking it again changes nothing').toBe(200)
    expect((await call('POST', '/mock-jira/tickets/MOCK-999/done')).status).toBe(404)

    const after = row(await watchlist(), 'Redis')
    expect(after).toMatchObject({ status: 'up_to_date', our_version: '8.2.1', open_ticket: null })
    expect(after.our_version_source).toMatchObject({ kind: 'ticket_done', ticket: key })
  })

  it('drops the tickets when the check is declined, so the software is behind again', async () => {
    const runId = await checkNow()
    await decide(await untilWaiting(runId), 'decline')
    const view = await watchlist()
    expect(row(view, 'LangGraph').status).toBe('behind')
    expect(row(view, 'Redis')).toMatchObject({ status: 'behind', approval_id: null, open_ticket: null })
  })
})

describe('nextStart', () => {
  const friday = Date.parse('2026-11-27T02:14:00Z')

  it('finds the next start in Singapore time', () => {
    expect(nextStart('monday', '09:00', friday)).toBe('2026-11-30T01:00:00.000Z')
    expect(nextStart('friday', '10:15', friday), 'later the same day').toBe('2026-11-27T02:15:00.000Z')
    expect(nextStart('friday', '10:10', friday), 'a week on once the time has passed').toBe('2026-12-04T02:10:00.000Z')
    expect(nextStart('every_day', '06:30', friday)).toBe('2026-11-27T22:30:00.000Z')
  })
})
