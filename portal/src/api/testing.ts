import type { OidcClient, OidcUser } from './oidc'

type Listener<T> = (value: T) => void

export interface FakeOidcClient extends OidcClient {
  readonly calls: string[]
  readonly fire: {
    userLoaded(user: OidcUser): void
    userUnloaded(): void
    silentRenewError(): void
    accessTokenExpiring(): void
    accessTokenExpired(): void
  }
  renewWith(outcome: OidcUser | null | Error | Promise<OidcUser | null>): void
}

interface FakeOptions {
  readonly stored?: OidcUser | null
  readonly callback?: OidcUser | Error
  readonly signOut?: Error
}

interface UserOptions {
  readonly expiresInS?: number
  readonly refresh?: boolean
  readonly sub?: string
  readonly state?: unknown
}

export function fakeUser(token: string, now: number, { expiresInS = 3600, refresh = true, sub = 'subject-1', state }: UserOptions = {}): OidcUser {
  return {
    access_token: token,
    ...(refresh ? { refresh_token: `refresh-${token}` } : {}),
    expires_at: Math.floor(now / 1000) + expiresInS,
    profile: { sub },
    state,
  }
}

export function fakeOidcClient({ stored = null, callback, signOut }: FakeOptions = {}): FakeOidcClient {
  const loaded = new Set<Listener<OidcUser>>()
  const unloaded = new Set<Listener<void>>()
  const renewErrors = new Set<Listener<Error>>()
  const expiring = new Set<Listener<void>>()
  const expired = new Set<Listener<void>>()
  const calls: string[] = []
  let renew: OidcUser | null | Error | Promise<OidcUser | null> = null

  const on =
    <T>(set: Set<Listener<T>>) =>
    (cb: Listener<T>) => {
      set.add(cb)
      return () => {
        set.delete(cb)
      }
    }
  const raise = <T>(set: Set<Listener<T>>, value: T) => {
    for (const cb of set) cb(value)
  }

  return {
    calls,
    events: {
      addUserLoaded: on(loaded),
      addUserUnloaded: on(unloaded),
      addSilentRenewError: on(renewErrors),
      addAccessTokenExpiring: on(expiring),
      addAccessTokenExpired: on(expired),
    },
    fire: {
      userLoaded: (user) => raise(loaded, user),
      userUnloaded: () => raise(unloaded, undefined),
      silentRenewError: () => raise(renewErrors, new Error('renew failed')),
      accessTokenExpiring: () => raise(expiring, undefined),
      accessTokenExpired: () => raise(expired, undefined),
    },
    renewWith: (outcome) => {
      renew = outcome
    },
    getUser: () => {
      calls.push('getUser')
      return Promise.resolve(stored)
    },
    signinRedirect: (args) => {
      calls.push(`signinRedirect ${JSON.stringify(args.state)}`)
      return Promise.resolve()
    },
    signinRedirectCallback: () => {
      calls.push('signinRedirectCallback')
      if (callback === undefined) return Promise.reject(new Error('not on the callback page'))
      return callback instanceof Error ? Promise.reject(callback) : Promise.resolve(callback)
    },
    signinSilent: () => {
      calls.push('signinSilent')
      return renew instanceof Error ? Promise.reject(renew) : Promise.resolve(renew)
    },
    signoutRedirect: () => {
      calls.push('signoutRedirect')
      return signOut ? Promise.reject(signOut) : Promise.resolve()
    },
    removeUser: () => {
      calls.push('removeUser')
      return Promise.resolve()
    },
  }
}
