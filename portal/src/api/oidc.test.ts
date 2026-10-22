import { describe, expect, it } from 'vitest'
import { bootOidc, CALLBACK_FAILED_WORDS, createOidcSession, INSECURE_WORDS, safeReturnPath, type BootPlace, type OidcUser } from './oidc'
import { authorizedFetch, SIGNED_IN, SIGNED_OUT, SignedOut } from './session'
import { fakeOidcClient, fakeUser } from './testing'

const NOW = Date.parse('2026-11-27T02:00:00Z')
const ORIGIN = 'http://portal.test'
const now = () => NOW

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('the OpenID Connect session', () => {
  it('signs with the bearer while the token is fresh', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, now)
    expect(await session.credentials()).toEqual({ Authorization: 'Bearer token-1' })
    expect(session.key()).toBe('subject-1')
    expect(client.calls).toEqual([])
  })

  it('renews once before the token ends, and every request waiting shares that renewal', async () => {
    const client = fakeOidcClient()
    const renewal = deferred<ReturnType<typeof fakeUser> | null>()
    client.renewWith(renewal.promise)
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 20 }), SIGNED_IN, now)
    const first = session.credentials()
    const second = session.credentials()
    renewal.resolve(fakeUser('token-2', NOW))
    expect(await first).toEqual({ Authorization: 'Bearer token-2' })
    expect(await second).toEqual({ Authorization: 'Bearer token-2' })
    expect(client.calls).toEqual(['signinSilent'])
    expect(await session.credentials()).toEqual({ Authorization: 'Bearer token-2' })
    expect(client.calls).toEqual(['signinSilent'])
  })

  it('renews once when the library says the token is about to end, and a request asking at the same time shares it', async () => {
    const client = fakeOidcClient()
    const renewal = deferred<OidcUser | null>()
    client.renewWith(renewal.promise)
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 20 }), SIGNED_IN, now)
    client.fire.accessTokenExpiring()
    expect(client.calls).toEqual(['signinSilent'])
    const request = session.credentials()
    renewal.resolve(fakeUser('token-2', NOW))
    expect(await request).toEqual({ Authorization: 'Bearer token-2' })
    expect(client.calls).toEqual(['signinSilent'])
  })

  it('lets a token with no refresh token run to its end when the library says it is about to end', () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 50, refresh: false }), SIGNED_IN, now)
    client.fire.accessTokenExpiring()
    expect(client.calls).toEqual([])
    expect(session.status()).toEqual({ kind: 'signed-in' })
  })

  it('finishes a renewal in flight before leaving to sign out, and a late renewal cannot sign the person back in', async () => {
    const client = fakeOidcClient()
    const renewal = deferred<OidcUser | null>()
    client.renewWith(renewal.promise)
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 20 }), SIGNED_IN, now)
    const request = session.credentials()
    const signOut = session.signOut()
    expect(client.calls).toEqual(['signinSilent'])
    renewal.resolve(fakeUser('token-2', NOW))
    expect(await request).toEqual({ Authorization: 'Bearer token-2' })
    await signOut
    expect(client.calls).toEqual(['signinSilent', 'signoutRedirect'])
    client.fire.userUnloaded()
    client.fire.userLoaded(fakeUser('token-3', NOW))
    expect(session.status()).toEqual({ kind: 'signed-out' })
    await expect(session.credentials()).rejects.toBeInstanceOf(SignedOut)
  })

  it('reports expired and sends nothing when the renewal fails', async () => {
    const client = fakeOidcClient()
    client.renewWith(new Error('refresh token revoked'))
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 5 }), SIGNED_IN, now)
    let sent = 0
    const platform: typeof fetch = () => {
      sent += 1
      return Promise.resolve(new Response('{}'))
    }
    const response = await authorizedFetch(session, platform, ORIGIN)('/api/v1/runs')
    expect(response.status).toBe(401)
    expect(sent).toBe(0)
    expect(session.status()).toEqual({ kind: 'expired' })
    await expect(session.credentials()).rejects.toBeInstanceOf(SignedOut)
  })

  it('reports expired without asking the provider when the ending token has no refresh token', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW, { expiresInS: 5, refresh: false }), SIGNED_IN, now)
    await expect(session.credentials()).rejects.toBeInstanceOf(SignedOut)
    expect(client.calls).toEqual([])
    expect(session.status()).toEqual({ kind: 'expired' })
  })

  it('signs with the token the library renews on its own', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, now)
    client.fire.userLoaded(fakeUser('token-2', NOW))
    expect(await session.credentials()).toEqual({ Authorization: 'Bearer token-2' })
    expect(session.status()).toEqual({ kind: 'signed-in' })
  })

  it.each([
    ['a silent renew error', (client: ReturnType<typeof fakeOidcClient>) => client.fire.silentRenewError()],
    ['the token expiring', (client: ReturnType<typeof fakeOidcClient>) => client.fire.accessTokenExpired()],
  ])('reports expired on %s and tells subscribers once', (_name, happen) => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, now)
    let told = 0
    session.subscribe(() => {
      told += 1
    })
    happen(client)
    session.rejected()
    expect(session.status()).toEqual({ kind: 'expired' })
    expect(told).toBe(1)
  })

  it('comes back to signed in when a renewal lands after the platform refused a token', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, now)
    session.rejected()
    await expect(session.credentials()).rejects.toBeInstanceOf(SignedOut)
    client.fire.userLoaded(fakeUser('token-2', NOW))
    expect(await session.credentials()).toEqual({ Authorization: 'Bearer token-2' })
  })

  it('cannot sign when signed out, and has no cache key', async () => {
    const session = createOidcSession(fakeOidcClient(), null, SIGNED_OUT, now)
    await expect(session.credentials()).rejects.toBeInstanceOf(SignedOut)
    expect(session.key()).toBe('')
  })

  it('leaves for the provider to sign in with the path to come back to, and to sign out', async () => {
    const client = fakeOidcClient()
    const session = createOidcSession(client, fakeUser('token-1', NOW), SIGNED_IN, now)
    await session.signIn('/approvals/apr_1?step=1')
    await session.signOut()
    expect(client.calls).toEqual(['signinRedirect {"returnTo":"/approvals/apr_1?step=1"}', 'signoutRedirect'])
    client.fire.userUnloaded()
    expect(session.status()).toEqual({ kind: 'signed-out' })
  })
})

describe('safeReturnPath', () => {
  it('keeps a path on this origin', () => {
    expect(safeReturnPath('/runs/run_1?x=1')).toBe('/runs/run_1?x=1')
    expect(safeReturnPath('/')).toBe('/')
  })

  it.each([['//evil.test/'], ['/\\evil.test'], ['https://evil.test/'], ['runs'], [42], [undefined], ['/auth/callback'], ['/signed-out']])(
    'sends %s to the start page',
    (raw) => {
      expect(safeReturnPath(raw)).toBe('/')
    },
  )
})

describe('bootOidc', () => {
  function place(pathname: string, { search = '', secure = true } = {}) {
    const replaced: string[] = []
    const at: BootPlace = { pathname, search, secure, replacePath: (path) => replaced.push(path) }
    return { at, replaced }
  }

  it('finishes the callback, moves the address to where the person was, and is signed in', async () => {
    const user = fakeUser('token-1', NOW, { state: { returnTo: '/approvals/apr_1' } })
    const client = fakeOidcClient({ callback: user })
    const { at, replaced } = place('/auth/callback', { search: '?code=abc&state=xyz' })
    const boot = await bootOidc(client, at, now)
    expect(boot.kind).toBe('session')
    if (boot.kind !== 'session') return
    expect(boot.session.status()).toEqual({ kind: 'signed-in' })
    expect(await boot.session.credentials()).toEqual({ Authorization: 'Bearer token-1' })
    expect(replaced).toEqual(['/approvals/apr_1'])
    expect(client.calls).toEqual(['signinRedirectCallback'])
  })

  it('reports a failed callback in plain words at the start page, and does not redirect again by itself', async () => {
    const client = fakeOidcClient({ callback: new Error('state mismatch') })
    const { at, replaced } = place('/auth/callback', { search: '?error=access_denied' })
    const boot = await bootOidc(client, at, now)
    expect(boot.kind === 'session' && boot.session.status()).toEqual({ kind: 'failed', message: CALLBACK_FAILED_WORDS })
    expect(replaced).toEqual(['/'])
    expect(client.calls).toEqual(['signinRedirectCallback'])
  })

  it('shows the signed-out page on /signed-out without asking the provider', async () => {
    const client = fakeOidcClient({ stored: fakeUser('token-1', NOW) })
    const boot = await bootOidc(client, place('/signed-out').at, now)
    expect(boot.kind === 'session' && boot.session.status()).toEqual({ kind: 'signed-out' })
    expect(client.calls).toEqual([])
  })

  it('is signed in with a stored token that has not ended', async () => {
    const client = fakeOidcClient({ stored: fakeUser('token-1', NOW) })
    const boot = await bootOidc(client, place('/runs/run_1').at, now)
    expect(boot.kind === 'session' && boot.session.status()).toEqual({ kind: 'signed-in' })
    expect(client.calls).toEqual(['getUser'])
  })

  it('renews a stored token that has ended when it has a refresh token', async () => {
    const client = fakeOidcClient({ stored: fakeUser('token-1', NOW, { expiresInS: -60 }) })
    client.renewWith(fakeUser('token-2', NOW))
    const boot = await bootOidc(client, place('/runs/run_1').at, now)
    expect(boot.kind).toBe('session')
    if (boot.kind !== 'session') return
    expect(await boot.session.credentials()).toEqual({ Authorization: 'Bearer token-2' })
    expect(client.calls).toEqual(['getUser', 'signinSilent'])
  })

  it('leaves for the provider when the stored token has ended and cannot be renewed', async () => {
    const client = fakeOidcClient({ stored: fakeUser('token-1', NOW, { expiresInS: -60 }) })
    client.renewWith(new Error('refresh token expired'))
    const boot = await bootOidc(client, place('/runs/run_1', { search: '?tab=minutes' }).at, now)
    expect(boot).toEqual({ kind: 'redirecting' })
    expect(client.calls).toEqual(['getUser', 'signinSilent', 'signinRedirect {"returnTo":"/runs/run_1?tab=minutes"}'])
  })

  it('leaves for the provider with the current path when nobody is signed in', async () => {
    const client = fakeOidcClient()
    const boot = await bootOidc(client, place('/approvals').at, now)
    expect(boot).toEqual({ kind: 'redirecting' })
    expect(client.calls).toEqual(['getUser', 'signinRedirect {"returnTo":"/approvals"}'])
  })

  it('cannot sign in outside a secure context, and says so without touching the provider', async () => {
    const client = fakeOidcClient({ stored: fakeUser('token-1', NOW) })
    const boot = await bootOidc(client, place('/', { secure: false }).at, now)
    expect(boot.kind === 'session' && boot.session.status()).toEqual({ kind: 'failed', message: INSECURE_WORDS })
    expect(client.calls).toEqual([])
  })
})
