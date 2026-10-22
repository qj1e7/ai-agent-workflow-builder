import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDemoPlatform } from '../mock'
import { ApiError, createApiClient, unwrap } from './client'
import { loadConfig, parseConfig, PortalConfigError } from './config'
import { fetchEventPage, refusalOf } from './queries'

const LIVE_DEV = { mode: 'live', signIn: { kind: 'dev' } }
const AUTH = { authority: 'https://login.example.test/tenant/v2.0', client_id: 'portal', scope: 'openid profile offline_access' }

describe('parseConfig', () => {
  it('reads demo mode, and live mode with dev sign-in when there are no sign-in settings', () => {
    expect(parseConfig({ mode: 'demo' })).toEqual({ mode: 'demo' })
    expect(parseConfig({ mode: 'live' })).toEqual(LIVE_DEV)
    for (const junk of [null, 42, 'demo', [], {}, { mode: 'DEMO' }, { mode: 7 }]) {
      expect(parseConfig(junk)).toEqual(LIVE_DEV)
    }
  })

  it('reads OpenID Connect sign-in settings', () => {
    expect(parseConfig({ mode: 'live', auth: AUTH })).toEqual({
      mode: 'live',
      signIn: { kind: 'oidc', authority: AUTH.authority, clientId: 'portal', scope: AUTH.scope },
    })
    expect(parseConfig({ mode: 'live', auth: { ...AUTH, authority: 'http://mock-oidc:8080/default' } })).toMatchObject({
      signIn: { authority: 'http://mock-oidc:8080/default' },
    })
  })

  it.each([
    ['no object', 'not an object'],
    ['no authority', { ...AUTH, authority: undefined }],
    ['a relative authority', { ...AUTH, authority: '/tenant/v2.0' }],
    ['a non-http authority', { ...AUTH, authority: 'ftp://login.example.test' }],
    ['an empty client id', { ...AUTH, client_id: '' }],
    ['no client id', { ...AUTH, client_id: 7 }],
    ['a scope without openid', { ...AUTH, scope: 'profile offline_access' }],
    ['a scope that only contains the word', { ...AUTH, scope: 'openidx' }],
  ])('refuses sign-in settings with %s rather than falling back to dev sign-in', (_name, auth) => {
    expect(() => parseConfig({ mode: 'live', auth })).toThrow(PortalConfigError)
  })

  it('refuses sign-in settings in demo mode', () => {
    expect(() => parseConfig({ mode: 'demo', auth: AUTH })).toThrow(PortalConfigError)
  })
})

describe('loadConfig', () => {
  it('falls back to live dev sign-in when the file is missing, broken or unreachable', async () => {
    expect(await loadConfig(() => Promise.resolve(new Response('nope', { status: 404 })))).toEqual(LIVE_DEV)
    expect(await loadConfig(() => Promise.resolve(new Response('{oops')))).toEqual(LIVE_DEV)
    expect(await loadConfig(() => Promise.reject(new Error('offline')))).toEqual(LIVE_DEV)
    expect(await loadConfig(() => Promise.resolve(new Response('{"mode":"demo"}')))).toEqual({ mode: 'demo' })
  })

  it('reads sign-in settings, and lets a bad set through as an error', async () => {
    const body = JSON.stringify({ mode: 'live', auth: AUTH })
    expect(await loadConfig(() => Promise.resolve(new Response(body)))).toMatchObject({ signIn: { kind: 'oidc' } })
    const bad = JSON.stringify({ mode: 'live', auth: { ...AUTH, scope: 'profile' } })
    await expect(loadConfig(() => Promise.resolve(new Response(bad)))).rejects.toThrow(PortalConfigError)
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
