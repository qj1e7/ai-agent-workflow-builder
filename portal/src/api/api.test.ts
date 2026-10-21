import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDemoPlatform } from '../mock'
import { ApiError, createApiClient, unwrap } from './client'
import { loadConfig, parseConfig } from './config'
import { fetchEventPage, refusalOf } from './queries'

describe('parseConfig', () => {
  it('reads demo mode and treats anything else as live', () => {
    expect(parseConfig({ mode: 'demo' })).toEqual({ mode: 'demo' })
    expect(parseConfig({ mode: 'live' })).toEqual({ mode: 'live' })
    for (const junk of [null, 42, 'demo', [], {}, { mode: 'DEMO' }, { mode: 7 }]) {
      expect(parseConfig(junk)).toEqual({ mode: 'live' })
    }
  })

  it('falls back to live when the file is missing, broken or unreachable', async () => {
    expect(await loadConfig(() => Promise.resolve(new Response('nope', { status: 404 })))).toEqual({ mode: 'live' })
    expect(await loadConfig(() => Promise.resolve(new Response('{oops')))).toEqual({ mode: 'live' })
    expect(await loadConfig(() => Promise.reject(new Error('offline')))).toEqual({ mode: 'live' })
    expect(await loadConfig(() => Promise.resolve(new Response('{"mode":"demo"}')))).toEqual({ mode: 'demo' })
  })
})

describe('the API client against the demo platform', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse('2026-11-27T02:00:00Z') })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  function clientFor(user: string) {
    const demo = createDemoPlatform()
    return createApiClient(demo.fetch, () => user, 'http://portal.test')
  }

  it('sends the dev user and gets typed answers back', async () => {
    const client = clientFor('bob')
    await vi.advanceTimersByTimeAsync(20_000)
    const approval = unwrap(
      await client.GET('/api/v1/approvals/{approval_id}', { params: { path: { approval_id: 'apr_01JB8' } } }),
    )
    expect(approval.you_can_decide).toBe(true)
    expect(unwrap(await client.GET('/api/v1/runs')).runs).toHaveLength(3)
  })

  it('reads a page of events as JSON', async () => {
    const client = clientFor('alice')
    await vi.advanceTimersByTimeAsync(20_000)
    const page = await fetchEventPage(client, 'run_01JB8', 15)
    expect(page.events.map((event) => event.seq)).toEqual([16, 17])
  })

  it('turns a refusal into an ApiError that refusalOf can read', async () => {
    const client = clientFor('alice')
    await vi.advanceTimersByTimeAsync(20_000)
    const attempt = async () =>
      unwrap(
        await client.POST('/api/v1/approvals/{approval_id}/decisions', {
          params: { path: { approval_id: 'apr_01JB8' } },
          body: { step: 0, verdict: 'approve', digest: 'sha256:0be2129632d1283e015efcae22757aa3e182793e0153503bdd30dc0327a42576' },
        }),
      )
    const error = await attempt().catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(refusalOf(error)?.refusal).toBe('own_work')
    expect((error as ApiError).message).toBe('You started this run, so another Approver must decide.')
  })
})
