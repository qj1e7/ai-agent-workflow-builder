import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import { createApiClient, type ApiClient } from './client'
import { wallClock, type RunClock } from './clock'
import type { PortalMode } from './config'
import { errorWords } from './errors'
import { authorizedFetch, type Session, type SessionStatus } from './session'

export interface ApiEnvironment {
  readonly mode: PortalMode
  readonly session: Session
  /** The platform's fetch, already signing requests. */
  readonly fetch: typeof fetch
  readonly client: ApiClient
  readonly clock: RunClock
}

const ApiContext = createContext<ApiEnvironment | null>(null)

interface ApiProviderProps {
  mode: PortalMode
  session: Session
  /** The platform's raw fetch. It is wrapped once with authorizedFetch, so nothing else attaches credentials. */
  fetch: typeof fetch
  clock?: RunClock
  baseUrl?: string
  origin?: string
  children: ReactNode
}

export function ApiProvider({
  mode,
  session,
  fetch: platformFetch,
  clock = wallClock,
  baseUrl = '',
  origin = window.location.origin,
  children,
}: ApiProviderProps) {
  const value = useMemo<ApiEnvironment>(() => {
    const fetchImpl = authorizedFetch(session, platformFetch, origin)
    return { mode, session, fetch: fetchImpl, clock, client: createApiClient(fetchImpl, baseUrl) }
  }, [mode, session, platformFetch, clock, baseUrl, origin])
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

function useEnvironment(): ApiEnvironment {
  const value = useContext(ApiContext)
  if (!value) throw new Error('ApiProvider is missing above this component.')
  return value
}

export function useApiClient(): ApiClient {
  return useEnvironment().client
}

export function useApiFetch(): typeof fetch {
  return useEnvironment().fetch
}

export function useRunClock(): RunClock {
  return useEnvironment().clock
}

export function usePortalMode(): PortalMode {
  return useEnvironment().mode
}

export function useSession(): Session {
  return useEnvironment().session
}

export function useSessionKey(): string {
  const session = useSession()
  return useSyncExternalStore(session.subscribe, session.key, session.key)
}

export function useSessionStatus(): SessionStatus {
  const session = useSession()
  return useSyncExternalStore(session.subscribe, session.status, session.status)
}

/** errorWords bound to the session kind, so a 401 asks for the right kind of sign-in. */
export function useErrorWords(): (error: unknown) => string {
  const { kind } = useSession()
  return (error) => errorWords(error, kind)
}
