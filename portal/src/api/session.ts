export type SessionKind = 'dev' | 'oidc'

export type SessionStatus =
  | { readonly kind: 'signed-in' }
  | { readonly kind: 'signed-out' }
  | { readonly kind: 'expired' }
  | { readonly kind: 'failed'; readonly message: string }

export const SIGNED_IN: SessionStatus = { kind: 'signed-in' }
export const SIGNED_OUT: SessionStatus = { kind: 'signed-out' }
export const EXPIRED: SessionStatus = { kind: 'expired' }

export type Credentials = Readonly<Record<string, string>>

export class SignedOut extends Error {
  constructor() {
    super('Not signed in.')
    this.name = 'SignedOut'
  }
}

interface SessionBase {
  cacheScope(this: void): string
  /** One stable object per state, so useSyncExternalStore compares by identity. */
  status(this: void): SessionStatus
  subscribe(this: void, listener: () => void): () => void
  credentials(this: void): Promise<Credentials>
  refusedByPlatform(this: void): void
}

export interface DevSession extends SessionBase {
  readonly kind: 'dev'
  choose(this: void, id: string): void
}

export interface OidcSession extends SessionBase {
  readonly kind: 'oidc'
  signIn(this: void, returnTo: string): Promise<void>
  signOut(this: void): Promise<void>
}

export type Session = DevSession | OidcSession

export const DEFAULT_DEV_USER = 'alice'
const STORAGE_KEY = 'portal.dev-user'

export type DevUserStore = Pick<Storage, 'getItem' | 'setItem'>

function localStore(): DevUserStore | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function storedDevUser(store: DevUserStore | null): string {
  try {
    return store?.getItem(STORAGE_KEY) || DEFAULT_DEV_USER
  } catch {
    return DEFAULT_DEV_USER
  }
}

export function createDevSession(store: DevUserStore | null = localStore()): DevSession {
  const listeners = new Set<() => void>()
  let current = storedDevUser(store)
  return {
    kind: 'dev',
    cacheScope: () => current,
    status: () => SIGNED_IN,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    credentials: () => Promise.resolve({ 'X-Dev-User': current }),
    refusedByPlatform: () => undefined,
    choose: (id) => {
      if (id === current) return
      current = id
      try {
        store?.setItem(STORAGE_KEY, id)
      } catch {
        // The choice still holds for this tab when storage is blocked.
      }
      for (const listener of listeners) listener()
    },
  }
}

const API_PREFIX = '/api/'

function requestFor(input: RequestInfo | URL, init: RequestInit | undefined, origin: string): Request {
  // A relative path resolves against the Portal's origin, so Node and the browser build the same URL.
  return new Request(typeof input === 'string' ? new URL(input, origin) : input, init)
}

function notSignedIn(): Response {
  return new Response(JSON.stringify({ detail: 'Not signed in.' }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function authorizedFetch(session: Session, fetchImpl: typeof fetch, origin: string): typeof fetch {
  return async (input, init) => {
    const request = requestFor(input, init, origin)
    const url = new URL(request.url)
    if (url.origin !== origin || !url.pathname.startsWith(API_PREFIX)) return fetchImpl(request)
    let credentials: Credentials
    try {
      credentials = await session.credentials()
    } catch (error) {
      if (error instanceof SignedOut) return notSignedIn()
      throw error
    }
    for (const [name, value] of Object.entries(credentials)) request.headers.set(name, value)
    const response = await fetchImpl(request)
    if (response.status === 401) session.refusedByPlatform()
    return response
  }
}
