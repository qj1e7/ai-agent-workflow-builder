import teamsStub from '@contracts/fixtures/stubs/teams-messages.json'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActivityEvent, ApprovalView, DecisionOut, RunView } from '../api/types'
import { fixtures } from './fixtures'
import { createDemoPlatform, type DemoPlatformHandle } from './index'

const START = Date.parse('2026-11-27T02:00:00Z')
const ORIGIN = 'http://portal.test/api/v1'
const SECOND = 1000
// The success run's pace, from the schedule in timeline.test.ts: the pause lands at 17.7 s and Bob's recorded decision at 32.6 s.
const PAUSE_MS = 17_745
const DECIDED_MS = 32_566

let demo: DemoPlatformHandle

beforeEach(() => {
  vi.useFakeTimers({ now: START })
  demo = createDemoPlatform(START)
})

afterEach(() => {
  vi.useRealTimers()
})

interface Options {
  user?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

async function call(method: string, path: string, options: Options = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  headers.set('X-Dev-User', options.user ?? 'alice')
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  const init: RequestInit = { method, headers }
  if (options.body !== undefined) init.body = JSON.stringify(options.body)
  if (options.signal) init.signal = options.signal
  return demo.fetch(`${ORIGIN}${path}`, init)
}

async function get<T>(path: string, user = 'alice'): Promise<T> {
  return (await (await call('GET', path, { user })).json()) as T
}

const runView = (runId: string, user = 'alice') => get<RunView>(`/runs/${runId}`, user)

async function eventsOf(runId: string, after = 0): Promise<ActivityEvent[]> {
  return (await get<{ events: ActivityEvent[] }>(`/runs/${runId}/events?after=${after}`)).events
}

async function startRun(user: string, key: string = crypto.randomUUID()): Promise<string> {
  const response = await call('POST', `/use-cases/${fixtures.useCase.use_case_id}/runs`, {
    user,
    headers: { 'Idempotency-Key': key },
  })
  expect(response.status).toBe(201)
  return ((await response.json()) as { run_id: string }).run_id
}

async function waitingApproval(runId: string): Promise<ApprovalView> {
  await vi.advanceTimersByTimeAsync(20 * SECOND)
  const view = await runView(runId)
  if (view.state !== 'awaiting_approval') throw new Error(`expected a pause, got ${view.state}`)
  return get<ApprovalView>(`/approvals/${view.approval.approval_id}`, 'bob')
}

function decision(approval: ApprovalView, verdict: 'approve' | 'decline') {
  return { step: 0, verdict, digest: approval.digest }
}

describe('the live success run', () => {
  it('pauses for approval and then continues when the recorded Bob approves, with the long wait squeezed', async () => {
    const runId = 'run_01JB8'
    expect((await runView(runId)).state).toBe('pending')

    await vi.advanceTimersByTimeAsync(PAUSE_MS - 500)
    expect((await runView(runId)).state).toBe('proposed')
    await vi.advanceTimersByTimeAsync(500)
    expect((await runView(runId)).state).toBe('awaiting_approval')

    await vi.advanceTimersByTimeAsync(DECIDED_MS - PAUSE_MS - 500)
    expect((await runView(runId)).state).toBe('awaiting_approval')

    await vi.advanceTimersByTimeAsync(500)
    expect((await runView(runId)).state).toBe('acting')

    await vi.advanceTimersByTimeAsync(4 * SECOND)
    const done = await runView(runId)
    expect(done.state).toBe('succeeded')
    expect(done.state === 'succeeded' && done.written[0]?.external_reference).toBe('MOCK-142')
  })

  it('reports recorded time and its rate through now, so the waiting counter shows the real six minutes and says it is sped up', async () => {
    await vi.advanceTimersByTimeAsync(18 * SECOND)
    const requested = (await eventsOf('run_01JB8')).find((event) => event.kind === 'approval_requested')
    expect(demo.now.rate('run_01JB8')).toBe(1)
    await vi.advanceTimersByTimeAsync(8 * SECOND)
    const waited = demo.now.now('run_01JB8') - Date.parse(requested?.ts ?? '')
    expect(waited).toBeGreaterThan(60 * SECOND)
    expect(waited).toBeLessThan(6 * 60 * SECOND)
    expect(demo.now.rate('run_01JB8')).toBe(40)
    expect(demo.now.rate('run_01JB9'), 'a finished run is never sped up').toBe(1)
  })

  it('posts the Teams message in the platform words, once the request is announced', async () => {
    await vi.advanceTimersByTimeAsync(20 * SECOND)
    const { messages } = await get<{ messages: { run_id: string; text: string }[] }>('/teams-stub/messages')
    expect(messages.find((message) => message.run_id === 'run_01JB8')?.text).toBe(teamsStub.messages[0]?.text)
  })

  it('lists the finished failure and rejected runs beside it, newest first', async () => {
    const { runs } = await get<{ runs: RunView[] }>('/runs')
    expect(runs.map((run) => [run.run_id, run.state])).toEqual([
      ['run_01JB8', 'pending'],
      ['run_01JB9', 'failed'],
      ['run_01JBA', 'rejected'],
    ])
  })
})

describe('event feed', () => {
  it('serves JSON pages after a sequence number', async () => {
    await vi.advanceTimersByTimeAsync(40 * SECOND)
    const page = await eventsOf('run_01JB8', 17)
    expect(page.map((event) => event.seq)).toEqual([18, 19, 20, 21, 22, 23])
  })

  async function open(after: Record<string, string>, controller: AbortController) {
    const response = await call('GET', '/runs/run_01JB8/events', {
      headers: { Accept: 'text/event-stream', ...after },
      signal: controller.signal,
    })
    const reader = (response.body as ReadableStream<Uint8Array>).getReader()
    const chunks: string[] = []
    const pump = (async () => {
      const decoder = new TextDecoder()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) return
        chunks.push(decoder.decode(value))
      }
    })()
    return { response, chunks, pump }
  }

  const seqsIn = (chunks: string[]) =>
    [...chunks.join('').matchAll(/^id: (\d+)$/gm)].map((match) => Number(match[1]))

  it('streams frames in the SSE format and keeps up with the replay', async () => {
    const controller = new AbortController()
    const { response, chunks, pump } = await open({}, controller)
    expect(response.headers.get('Content-Type')).toBe('text/event-stream')

    await vi.advanceTimersByTimeAsync(3 * SECOND)
    expect(seqsIn(chunks)).toEqual([1, 2, 3, 4, 5])
    expect(chunks.join('')).toMatch(/^id: 1\nevent: activity\ndata: \{.*"kind":"run_created".*\}\n\n/)

    await vi.advanceTimersByTimeAsync(40 * SECOND)
    expect(seqsIn(chunks)).toEqual(Array.from({ length: 23 }, (_, index) => index + 1))
    controller.abort()
    await pump
  })

  it('resumes after Last-Event-ID without repeating events', async () => {
    await vi.advanceTimersByTimeAsync(15 * SECOND)
    const controller = new AbortController()
    const { chunks, pump } = await open({ 'Last-Event-ID': '16' }, controller)
    await vi.advanceTimersByTimeAsync(30 * SECOND)
    expect(seqsIn(chunks)).toEqual([17, 18, 19, 20, 21, 22, 23])
    controller.abort()
    await pump
  })

  it('closes cleanly when the request is aborted and sends nothing more', async () => {
    const controller = new AbortController()
    const { chunks, pump } = await open({}, controller)
    await vi.advanceTimersByTimeAsync(SECOND)
    controller.abort()
    await pump
    const sent = chunks.length
    await vi.advanceTimersByTimeAsync(30 * SECOND)
    expect(chunks).toHaveLength(sent)
  })
})

describe('approvals on a run started from a use case', () => {
  it('refuses the starter and a non-approver, and never approves by itself', async () => {
    const runId = await startRun('alice')
    const approval = await waitingApproval(runId)

    const own = await call('POST', `/approvals/${approval.approval_id}/decisions`, {
      user: 'alice',
      body: decision(approval, 'approve'),
    })
    expect(own.status).toBe(403)
    expect(await own.json()).toEqual({ refusal: 'own_work', message: fixtures.ownWorkRefusal.message })

    const outsider = await call('POST', `/approvals/${approval.approval_id}/decisions`, {
      user: 'carol',
      body: decision(approval, 'approve'),
    })
    expect(outsider.status).toBe(403)
    expect(((await outsider.json()) as { refusal: string }).refusal).toBe('not_an_approver')

    await vi.advanceTimersByTimeAsync(30 * 60 * SECOND)
    expect((await runView(runId)).state).toBe('awaiting_approval')
  })

  it('tells each caller whether they can decide', async () => {
    const approval = await waitingApproval(await startRun('alice'))
    const asAlice = await get<ApprovalView>(`/approvals/${approval.approval_id}`, 'alice')
    expect([asAlice.you_can_decide, asAlice.why_not]).toEqual([false, 'own_work'])
    expect([approval.you_can_decide, approval.why_not]).toEqual([true, null])
  })

  it('continues to success when Bob approves, writing a new Jira ticket and a Teams message', async () => {
    const runId = await startRun('alice')
    const approval = await waitingApproval(runId)

    const response = await call('POST', `/approvals/${approval.approval_id}/decisions`, {
      user: 'bob',
      body: decision(approval, 'approve'),
    })
    expect(response.status).toBe(201)
    const out = (await response.json()) as DecisionOut
    expect([out.status, out.decision.by, out.decision.verdict]).toEqual(['approved', 'bob', 'approve'])

    await vi.advanceTimersByTimeAsync(5 * SECOND)
    const events = await eventsOf(runId)
    expect(events.at(-1)?.kind).toBe('run_succeeded')
    expect(events.map((event) => event.seq)).toEqual(Array.from({ length: 23 }, (_, index) => index + 1))
    expect(events.every((event) => event.run_id === runId)).toBe(true)
    expect(events[0]?.summary).toBe('Alice started a run of LangGraph releases.')

    const { tickets } = await get<{ tickets: { key: string; run_id: string }[] }>('/mock-jira/tickets')
    expect(tickets.find((ticket) => ticket.run_id === runId)?.key).toBe('MOCK-143')

    const { messages } = await get<{ messages: { run_id: string; approval_id: string; link: string }[] }>(
      '/teams-stub/messages',
    )
    const message = messages.find((candidate) => candidate.run_id === runId)
    expect(message?.approval_id).toBe(approval.approval_id)
    expect(message?.link).toBe(`/approvals/${approval.approval_id}`)
  })

  it('answers the same decision twice with the recorded one and a different one with 409', async () => {
    const approval = await waitingApproval(await startRun('alice'))
    const path = `/approvals/${approval.approval_id}/decisions`
    expect((await call('POST', path, { user: 'bob', body: decision(approval, 'approve') })).status).toBe(201)

    const again = await call('POST', path, { user: 'bob', body: decision(approval, 'approve') })
    expect(again.status).toBe(200)
    expect(((await again.json()) as DecisionOut).decision.by).toBe('bob')

    expect((await call('POST', path, { user: 'bob', body: decision(approval, 'decline') })).status).toBe(409)
  })

  it('ends in run_rejected when an Approver declines, and writes nothing', async () => {
    const runId = await startRun('alice')
    const approval = await waitingApproval(runId)
    const before = (await get<{ tickets: unknown[] }>('/mock-jira/tickets')).tickets.length

    await call('POST', `/approvals/${approval.approval_id}/decisions`, {
      user: 'bob',
      body: decision(approval, 'decline'),
    })
    await vi.advanceTimersByTimeAsync(2 * SECOND)

    const view = await runView(runId)
    expect(view.state).toBe('rejected')
    expect((await eventsOf(runId)).at(-1)?.kind).toBe('run_rejected')
    expect((await get<{ tickets: unknown[] }>('/mock-jira/tickets')).tickets).toHaveLength(before)
  })

  describe('a decision made before the Teams post lands', () => {
    async function pausedBeforeThePost() {
      await vi.advanceTimersByTimeAsync(PAUSE_MS)
      expect((await runView('run_01JB8')).state).toBe('awaiting_approval')
      expect((await eventsOf('run_01JB8')).some((event) => event.kind === 'approval_announced')).toBe(false)
      return get<ApprovalView>('/approvals/apr_01JB8', 'bob')
    }

    it('is answered with who made it, and the run plays on from there', async () => {
      const approval = await pausedBeforeThePost()
      const response = await call('POST', '/approvals/apr_01JB8/decisions', {
        user: 'bob',
        body: decision(approval, 'approve'),
      })
      expect(response.status).toBe(201)
      const out = (await response.json()) as DecisionOut
      expect([out.status, out.decision.by, out.decision.verdict]).toEqual(['approved', 'bob', 'approve'])

      const after = await get<ApprovalView>('/approvals/apr_01JB8', 'bob')
      expect([after.steps[0]?.status, after.steps[0]?.decided_by, after.you_can_decide]).toEqual([
        'approved',
        'bob',
        false,
      ])

      await vi.advanceTimersByTimeAsync(10 * SECOND)
      const events = await eventsOf('run_01JB8')
      const kinds = events.map((event) => event.kind)
      expect(events.map((event) => event.seq)).toEqual(Array.from({ length: 23 }, (_, index) => index + 1))
      expect(kinds.indexOf('approval_announced')).toBeLessThan(kinds.indexOf('approval_decided'))
      expect(kinds.filter((kind) => kind === 'approval_decided')).toHaveLength(1)
      expect(kinds.at(-1)).toBe('run_succeeded')
      const { tickets } = await get<{ tickets: { key: string; run_id: string }[] }>('/mock-jira/tickets')
      expect(tickets.filter((ticket) => ticket.run_id === 'run_01JB8').map((ticket) => ticket.key)).toEqual([
        'MOCK-143',
      ])
    })

    it('answers a repeat with the recorded decision and a different verdict with 409', async () => {
      const approval = await pausedBeforeThePost()
      const path = '/approvals/apr_01JB8/decisions'
      expect((await call('POST', path, { user: 'bob', body: decision(approval, 'approve') })).status).toBe(201)

      const again = await call('POST', path, { user: 'bob', body: decision(approval, 'approve') })
      expect(again.status).toBe(200)
      expect(((await again.json()) as DecisionOut).decision.by).toBe('bob')
      expect((await call('POST', path, { user: 'bob', body: decision(approval, 'decline') })).status).toBe(409)

      await vi.advanceTimersByTimeAsync(10 * SECOND)
      const { tickets } = await get<{ tickets: { key: string; run_id: string }[] }>('/mock-jira/tickets')
      expect(tickets.filter((ticket) => ticket.run_id === 'run_01JB8').map((ticket) => ticket.key)).toEqual([
        'MOCK-143',
      ])
    })
  })

  it('lets a real decision replace the recorded one on the live run', async () => {
    await vi.advanceTimersByTimeAsync(18 * SECOND)
    const approval = await get<ApprovalView>('/approvals/apr_01JB8', 'bob')
    await call('POST', '/approvals/apr_01JB8/decisions', { user: 'bob', body: decision(approval, 'decline') })
    await vi.advanceTimersByTimeAsync(60 * SECOND)
    const events = await eventsOf('run_01JB8')
    expect(events.map((event) => event.kind).filter((kind) => kind === 'approval_decided')).toHaveLength(1)
    expect(events.at(-1)?.kind).toBe('run_rejected')
  })
})

describe('starting and retrying runs', () => {
  it('returns the same run for the same Idempotency-Key', async () => {
    const first = await startRun('alice', 'click-1')
    const second = await startRun('alice', 'click-1')
    const third = await startRun('alice', 'click-2')
    expect(second).toBe(first)
    expect(third).not.toBe(first)
    const { runs } = await get<{ runs: RunView[] }>('/runs')
    expect(runs).toHaveLength(5)
  })

  it('replays the work leg as attempt 2 after a retry, then waits for a decision', async () => {
    const response = await call('POST', '/runs/run_01JB9/retry', { user: 'alice' })
    expect(response.status).toBe(202)
    expect(await response.json()).toEqual({ state: 'pending' })

    const events = await eventsOf('run_01JB9')
    expect(events.at(-1)).toMatchObject({ seq: 13, kind: 'run_retried', summary: 'Alice retried the run.' })
    expect((await runView('run_01JB9')).state).toBe('pending')

    await vi.advanceTimersByTimeAsync(22 * SECOND)
    const replayed = await eventsOf('run_01JB9', 12)
    expect(replayed.map((event) => event.seq)).toEqual(Array.from({ length: 17 }, (_, index) => index + 13))
    expect(replayed.find((event) => event.kind === 'leg_dispatched')?.data).toEqual({ leg: 'work', attempt: 2 })

    await vi.advanceTimersByTimeAsync(10 * 60 * SECOND)
    expect((await runView('run_01JB9')).state).toBe('awaiting_approval')
  })

  it('refuses to retry a run that has not failed', async () => {
    expect((await call('POST', '/runs/run_01JBA/retry')).status).toBe(409)
  })

  it('explains a failed run and nothing else', async () => {
    const advice = await call('GET', '/runs/run_01JB9/troubleshoot')
    expect(await advice.json()).toEqual(fixtures.troubleshooting)
    expect((await call('GET', '/runs/run_01JB8/troubleshoot')).status).toBe(404)
  })
})

describe('use cases and the Room lead', () => {
  it('suggests the release check for releases and tickets, and nothing otherwise', async () => {
    const hit = await call('POST', '/use-cases/suggest', {
      body: { text: 'Every Monday, check the repo for new releases. If there are any, open a Jira ticket.' },
    })
    expect(await hit.json()).toEqual({ template: fixtures.releaseCheck, matched_terms: ['releases', 'ticket'] })
    const miss = await call('POST', '/use-cases/suggest', { body: { text: 'Tidy my inbox' } })
    expect(await miss.json()).toEqual({ template: null, matched_terms: [] })
  })

  it('stores a use case and starts runs from it', async () => {
    const created = await call('POST', '/use-cases', {
      body: {
        template: 'release_check',
        name: 'Weekly check',
        instruction: 'Check for releases.',
        params: { repo: 'acme/widgets', ticket_project: 'MOCK' },
      },
    })
    expect(created.status).toBe(201)
    const { use_case_id: useCaseId } = (await created.json()) as { use_case_id: string }
    const { use_cases: useCases } = await get<{ use_cases: { use_case_id: string; owner: string }[] }>('/use-cases')
    expect(useCases[0]).toMatchObject({ use_case_id: useCaseId, owner: 'alice' })

    const started = await call('POST', `/use-cases/${useCaseId}/runs`, { headers: { 'Idempotency-Key': 'k' } })
    const { run_id: runId } = (await started.json()) as { run_id: string }
    const first = (await eventsOf(runId))[0]
    expect(first?.summary).toBe('Alice started a run of Weekly check.')
  })

  it('answers 401 without a known dev user', async () => {
    const response = await demo.fetch(`${ORIGIN}/runs`)
    expect(response.status).toBe(401)
  })
})
