import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, unwrap } from './client'
import { loadConfig, parseConfig, PortalConfigError } from './config'
import { fetchEventPage, refusalOf } from './queries'
import { authorizedFetch, createDevSession } from './session'

const LIVE_DEV = { mode: 'live', signIn: { kind: 'dev' }, jiraBrowseUrl: null }
const AUTH = { authority: 'https://login.example.test/tenant/v2.0', client_id: 'portal', scope: 'openid profile offline_access' }

describe('parseConfig', () => {
  it('reads live mode with dev sign-in when there are no sign-in settings', () => {
    expect(parseConfig({ mode: 'live' })).toEqual(LIVE_DEV)
    for (const junk of [null, 42, 'live', [], {}, { mode: 'demo' }, { mode: 7 }]) {
      expect(parseConfig(junk)).toEqual(LIVE_DEV)
    }
  })

  it('reads OpenID Connect sign-in settings', () => {
    expect(parseConfig({ mode: 'live', auth: AUTH })).toEqual({
      mode: 'live',
      jiraBrowseUrl: null,
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

})

describe('parseConfig and the Jira address', () => {
  const BROWSE = 'https://jira.example.test/browse/{key}'

  it('has no Jira address unless the file gives one, and treats an empty one as none', () => {
    expect(parseConfig({ mode: 'live' })).toMatchObject({ jiraBrowseUrl: null })
    expect(parseConfig({ mode: 'live', jira_browse_url: '' })).toMatchObject({ jiraBrowseUrl: null })
  })

  it('reads the address where tickets are viewed, next to the sign-in settings', () => {
    expect(parseConfig({ mode: 'live', jira_browse_url: BROWSE })).toMatchObject({ jiraBrowseUrl: BROWSE, signIn: { kind: 'dev' } })
    expect(parseConfig({ mode: 'live', auth: AUTH, jira_browse_url: BROWSE })).toMatchObject({ jiraBrowseUrl: BROWSE, signIn: { kind: 'oidc' } })
  })

  it.each([
    ['a relative address', '/browse/{key}'],
    ['a non-http address', 'ftp://jira.example.test/{key}'],
    ['an address without {key}', 'https://jira.example.test/browse/'],
    ['an address without a host', 'https:///{key}'],
    ['a number', 7],
  ])('refuses %s', (_name, value) => {
    expect(() => parseConfig({ mode: 'live', jira_browse_url: value })).toThrow(PortalConfigError)
  })
})

describe('loadConfig', () => {
  it('falls back to live dev sign-in when the file is missing, broken or unreachable', async () => {
    expect(await loadConfig(() => Promise.resolve(new Response('nope', { status: 404 })))).toEqual(LIVE_DEV)
    expect(await loadConfig(() => Promise.resolve(new Response('{oops')))).toEqual(LIVE_DEV)
    expect(await loadConfig(() => Promise.reject(new Error('offline')))).toEqual(LIVE_DEV)
  })

  it('reads sign-in settings, and lets a bad set through as an error', async () => {
    const body = JSON.stringify({ mode: 'live', auth: AUTH })
    expect(await loadConfig(() => Promise.resolve(new Response(body)))).toMatchObject({ signIn: { kind: 'oidc' } })
    const bad = JSON.stringify({ mode: 'live', auth: { ...AUTH, scope: 'profile' } })
    await expect(loadConfig(() => Promise.resolve(new Response(bad)))).rejects.toThrow(PortalConfigError)
  })
})

describe('the API client', () => {
  const json = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

  function clientFor(user: string, fetchImpl: typeof fetch) {
    const session = createDevSession(null)
    session.choose(user)
    return createApiClient(authorizedFetch(session, fetchImpl, 'http://portal.test'), 'http://portal.test')
  }

  it('sends the dev user and gets typed answers back', async () => {
    const seen: (string | null)[] = []
    const client = clientFor('bob', (input, init) => {
      seen.push(new Request(input, init).headers.get('X-Dev-User'))
      return json({ runs: [] })
    })
    expect(unwrap(await client.GET('/api/v1/runs')).runs).toEqual([])
    expect(seen).toEqual(['bob'])
  })

  it('reads a page of events as JSON', async () => {
    let accept: string | null = null
    let url = ''
    const client = clientFor('alice', (input, init) => {
      const request = new Request(input, init)
      accept = request.headers.get('accept')
      url = request.url
      return json({ events: [{ seq: 16 }, { seq: 17 }] })
    })
    const page = await fetchEventPage(client, 'run_01JB8', 15)
    expect(page.events.map((event) => event.seq)).toEqual([16, 17])
    expect(accept).toBe('application/json')
    expect(url).toBe('http://portal.test/api/v1/runs/run_01JB8/events?after=15')
  })

  it('turns a refusal into an ApiError that refusalOf can read', async () => {
    const message = 'This run is your own work, so another Approver must decide.'
    const client = clientFor('alice', () => json({ refusal: 'own_work', message }, 403))
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
    expect((error as ApiError).message).toBe(message)
  })
})
