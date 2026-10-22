import { describe, expect, it } from 'vitest'
import { createApiClient } from './client'
import { authorizedFetch, createDevSession, SIGNED_IN, SignedOut, type Credentials, type DevUserStore, type Session } from './session'

const ORIGIN = 'http://portal.test'

interface Sent {
  readonly url: string
  readonly method: string
  readonly headers: Headers
}

function platform(status = 200) {
  const sent: Sent[] = []
  const fetchImpl: typeof fetch = (input, init) => {
    const request = new Request(input, init)
    sent.push({ url: request.url, method: request.method, headers: request.headers })
    return Promise.resolve(new Response('{"runs":[]}', { status, headers: { 'Content-Type': 'application/json' } }))
  }
  return { sent, fetchImpl }
}

function signingSession(credentials: () => Promise<Credentials>) {
  let rejections = 0
  const session: Session = {
    kind: 'oidc',
    cacheScope: () => 'subject-1',
    status: () => SIGNED_IN,
    subscribe: () => () => undefined,
    credentials,
    refusedByPlatform: () => {
      rejections += 1
    },
    signIn: () => Promise.resolve(),
    signOut: () => Promise.resolve(),
  }
  return { session, rejections: () => rejections }
}

function memoryStore(): DevUserStore {
  const items = new Map<string, string>()
  return { getItem: (key) => items.get(key) ?? null, setItem: (key, value) => void items.set(key, value) }
}

const blockedStore: DevUserStore = {
  getItem: () => {
    throw new Error('blocked')
  },
  setItem: () => {
    throw new Error('blocked')
  },
}

describe('authorizedFetch', () => {
  it('sends the chosen dev user on a request the typed client builds', async () => {
    const { sent, fetchImpl } = platform()
    const session = createDevSession(null)
    const client = createApiClient(authorizedFetch(session, fetchImpl, ORIGIN), ORIGIN)
    await client.GET('/api/v1/runs')
    session.choose('bob')
    await client.GET('/api/v1/runs')
    expect(sent.map((request) => request.headers.get('X-Dev-User'))).toEqual(['alice', 'bob'])
    expect(sent[0]?.url).toBe(`${ORIGIN}/api/v1/runs`)
  })

  it('sends the bearer on the feed style call and keeps the headers the feed set', async () => {
    const { sent, fetchImpl } = platform()
    const { session } = signingSession(() => Promise.resolve({ Authorization: 'Bearer token-1' }))
    const fetchSigned = authorizedFetch(session, fetchImpl, ORIGIN)
    await fetchSigned('/api/v1/runs/run_1/events', { headers: { Accept: 'text/event-stream', 'Last-Event-ID': '17' } })
    const headers = sent[0]?.headers
    expect(headers?.get('Authorization')).toBe('Bearer token-1')
    expect(headers?.get('Accept')).toBe('text/event-stream')
    expect(headers?.get('Last-Event-ID')).toBe('17')
  })

  it('sends the bearer on a request the typed client builds, with the body and the idempotency key intact', async () => {
    const { sent, fetchImpl } = platform()
    const { session } = signingSession(() => Promise.resolve({ Authorization: 'Bearer token-1' }))
    const client = createApiClient(authorizedFetch(session, fetchImpl, ORIGIN), ORIGIN)
    await client.POST('/api/v1/use-cases/{use_case_id}/runs', {
      params: { path: { use_case_id: 'uc_1' }, header: { 'Idempotency-Key': 'key-1' } },
    })
    expect(sent[0]).toMatchObject({ method: 'POST', url: `${ORIGIN}/api/v1/use-cases/uc_1/runs` })
    expect(sent[0]?.headers.get('Authorization')).toBe('Bearer token-1')
    expect(sent[0]?.headers.get('Idempotency-Key')).toBe('key-1')
  })

  it.each([
    ['another origin', 'https://login.example.test/oauth2/token'],
    ['a path outside the API', `${ORIGIN}/config.json`],
    ['a relative path outside the API', '/assets/app.js'],
  ])('never signs a request to %s', async (_name, url) => {
    const { sent, fetchImpl } = platform()
    let asked = 0
    const { session } = signingSession(() => {
      asked += 1
      return Promise.resolve({ Authorization: 'Bearer token-1' })
    })
    await authorizedFetch(session, fetchImpl, ORIGIN)(url)
    expect(asked).toBe(0)
    expect(sent[0]?.headers.has('Authorization')).toBe(false)
  })

  it('tells the session when the platform answers 401, and only then', async () => {
    const ok = platform(200)
    const refused = platform(401)
    const { session, rejections } = signingSession(() => Promise.resolve({ Authorization: 'Bearer token-1' }))
    await authorizedFetch(session, ok.fetchImpl, ORIGIN)('/api/v1/runs')
    expect(rejections()).toBe(0)
    const response = await authorizedFetch(session, refused.fetchImpl, ORIGIN)('/api/v1/runs')
    expect(response.status).toBe(401)
    expect(rejections()).toBe(1)
  })

  it('is the only fetch the typed client takes', () => {
    const { fetchImpl } = platform()
    // @ts-expect-error a raw fetch carries no sign-in, so the client refuses it before anything runs
    createApiClient(fetchImpl, ORIGIN)
    expect(createApiClient(authorizedFetch(createDevSession(null), fetchImpl, ORIGIN), ORIGIN)).toBeDefined()
  })

  it('answers 401 itself and sends nothing when the session cannot sign', async () => {
    const { sent, fetchImpl } = platform()
    const { session, rejections } = signingSession(() => Promise.reject(new SignedOut()))
    const client = createApiClient(authorizedFetch(session, fetchImpl, ORIGIN), ORIGIN)
    const { response, error } = await client.GET('/api/v1/runs')
    expect(response.status).toBe(401)
    expect(error).toEqual({ detail: 'Not signed in.' })
    expect(sent).toHaveLength(0)
    expect(rejections()).toBe(0)
  })
})

describe('the dev session', () => {
  it('starts as alice, remembers the chosen user, and tells its subscribers', () => {
    const memory = memoryStore()
    const session = createDevSession(memory)
    let told = 0
    session.subscribe(() => {
      told += 1
    })
    expect(session.cacheScope()).toBe('alice')
    session.choose('carol')
    session.choose('carol')
    expect(session.cacheScope()).toBe('carol')
    expect(told).toBe(1)
    expect(createDevSession(memory).cacheScope()).toBe('carol')
    expect(session.status()).toEqual({ kind: 'signed-in' })
  })

  it('keeps the choice for the tab when storage is blocked', () => {
    const session = createDevSession(blockedStore)
    expect(session.cacheScope()).toBe('alice')
    session.choose('bob')
    expect(session.cacheScope()).toBe('bob')
  })
})
