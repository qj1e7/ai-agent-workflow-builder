import { UserManager, WebStorageStateStore } from 'oidc-client-ts'
import type { OidcSignIn } from './config'
import { EXPIRED, SIGNED_IN, SIGNED_OUT, SignedOut, type OidcSession, type SessionStatus } from './session'

export const CALLBACK_PATH = '/auth/callback'
export const SIGNED_OUT_PATH = '/signed-out'
export const RENEW_BEFORE_MS = 30_000

export const INSECURE_WORDS = 'Open the Portal over https or on localhost to sign in.'
export const CALLBACK_FAILED_WORDS = 'Sign-in did not finish. Try again.'

export interface OidcUser {
  readonly access_token: string
  readonly refresh_token?: string | undefined
  /** Epoch seconds. */
  readonly expires_at?: number | undefined
  readonly profile: { readonly sub: string }
  readonly state?: unknown
}

export interface OidcEvents {
  addUserLoaded(cb: (user: OidcUser) => void): () => void
  addUserUnloaded(cb: () => void): () => void
  addSilentRenewError(cb: (error: Error) => void): () => void
  addAccessTokenExpired(cb: () => void): () => void
}

export interface OidcClient {
  readonly events: OidcEvents
  getUser(): Promise<OidcUser | null>
  signinRedirect(args: { state: unknown }): Promise<void>
  signinRedirectCallback(): Promise<OidcUser>
  signinSilent(): Promise<OidcUser | null>
  signoutRedirect(): Promise<void>
  removeUser(): Promise<void>
}

export function oidcClientFor(config: OidcSignIn, origin: string): OidcClient {
  return new UserManager({
    authority: config.authority,
    client_id: config.clientId,
    scope: config.scope,
    redirect_uri: `${origin}${CALLBACK_PATH}`,
    post_logout_redirect_uri: `${origin}${SIGNED_OUT_PATH}`,
    response_type: 'code',
    automaticSilentRenew: true,
    loadUserInfo: false,
    monitorSession: false,
    revokeTokensOnSignout: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  })
}

function msLeft(user: OidcUser, now: number): number {
  return user.expires_at === undefined ? Number.POSITIVE_INFINITY : user.expires_at * 1000 - now
}

export function createOidcSession(client: OidcClient, user: OidcUser | null, initial: SessionStatus, now: () => number = Date.now): OidcSession {
  let current = user
  let status = initial
  let renewing: Promise<OidcUser | null> | null = null
  const listeners = new Set<() => void>()

  function become(next: SessionStatus): void {
    if (next === status) return
    status = next
    for (const listener of listeners) listener()
  }

  function load(next: OidcUser): void {
    current = next
    become(SIGNED_IN)
  }

  const expire = () => become(EXPIRED)

  function renew(): Promise<OidcUser | null> {
    if (!current?.refresh_token) {
      expire()
      return Promise.resolve(null)
    }
    renewing ??= client
      .signinSilent()
      .then(
        (renewed) => {
          if (renewed) load(renewed)
          else expire()
          return renewed
        },
        () => {
          expire()
          return null
        },
      )
      .finally(() => {
        renewing = null
      })
    return renewing
  }

  client.events.addUserLoaded(load)
  client.events.addUserUnloaded(() => become(SIGNED_OUT))
  client.events.addSilentRenewError(expire)
  client.events.addAccessTokenExpired(expire)

  return {
    kind: 'oidc',
    key: () => current?.profile.sub ?? '',
    status: () => status,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    credentials: async () => {
      if (status.kind !== 'signed-in' || !current) throw new SignedOut()
      const signer = msLeft(current, now()) < RENEW_BEFORE_MS ? await renew() : current
      if (!signer) throw new SignedOut()
      return { Authorization: `Bearer ${signer.access_token}` }
    },
    rejected: expire,
    signIn: (returnTo) => client.signinRedirect({ state: { returnTo } }),
    signOut: () => client.signoutRedirect(),
  }
}

export interface BootPlace {
  readonly pathname: string
  readonly search: string
  /** window.isSecureContext with crypto.subtle: PKCE needs both. */
  readonly secure: boolean
  replacePath(this: void, path: string): void
}

export type Boot = { readonly kind: 'session'; readonly session: OidcSession } | { readonly kind: 'redirecting' }

export function safeReturnPath(raw: unknown): string {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/'
  return raw === CALLBACK_PATH || raw === SIGNED_OUT_PATH ? '/' : raw
}

function returnToOf({ state }: OidcUser): unknown {
  return typeof state === 'object' && state !== null && 'returnTo' in state ? state.returnTo : undefined
}

export async function bootOidc(client: OidcClient, place: BootPlace, now: () => number = Date.now): Promise<Boot> {
  const session = (user: OidcUser | null, status: SessionStatus): Boot => ({
    kind: 'session',
    session: createOidcSession(client, user, status, now),
  })
  if (!place.secure) return session(null, { kind: 'failed', message: INSECURE_WORDS })
  if (place.pathname === CALLBACK_PATH) {
    try {
      const user = await client.signinRedirectCallback()
      place.replacePath(safeReturnPath(returnToOf(user)))
      return session(user, SIGNED_IN)
    } catch {
      place.replacePath('/')
      return session(null, { kind: 'failed', message: CALLBACK_FAILED_WORDS })
    }
  }
  if (place.pathname === SIGNED_OUT_PATH) return session(null, SIGNED_OUT)
  const stored = await client.getUser()
  if (stored && msLeft(stored, now()) > 0) return session(stored, SIGNED_IN)
  if (stored?.refresh_token) {
    const renewed = await client.signinSilent().catch(() => null)
    if (renewed) return session(renewed, SIGNED_IN)
  }
  await client.signinRedirect({ state: { returnTo: place.pathname + place.search } })
  return { kind: 'redirecting' }
}
