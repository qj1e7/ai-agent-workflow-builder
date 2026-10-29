import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react'
import { createApiClient, type ApiClient } from './client'
import { wallClock, type RunClock } from './clock'
import { errorWords } from './errors'
import { authorizedFetch, type Session, type SessionStatus, type SignedFetch } from './session'

export interface ApiEnvironment {
  readonly session: Session
  readonly fetch: SignedFetch
  readonly client: ApiClient
  readonly clock: RunClock
}

const ApiContext = createContext<ApiEnvironment | null>(null)

interface ApiProviderProps {
  session: Session
  platformFetch: typeof fetch
  clock?: RunClock
  baseUrl?: string
  origin?: string
  children: ReactNode
}

export function ApiProvider({
  session,
  platformFetch,
  clock = wallClock,
  baseUrl = '',
  origin = window.location.origin,
  children,
}: ApiProviderProps) {
  const value = useMemo<ApiEnvironment>(() => {
    const fetchImpl = authorizedFetch(session, platformFetch, origin)
    return { session, fetch: fetchImpl, clock, client: createApiClient(fetchImpl, baseUrl) }
  }, [session, platformFetch, clock, baseUrl, origin])
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

export function useApiFetch(): SignedFetch {
  return useEnvironment().fetch
}

export function useRunClock(): RunClock {
  return useEnvironment().clock
}

export function useSession(): Session {
  return useEnvironment().session
}

export function useCacheScope(): string {
  const session = useSession()
  return useSyncExternalStore(session.subscribe, session.cacheScope, session.cacheScope)
}

export function useSessionStatus(): SessionStatus {
  const session = useSession()
  return useSyncExternalStore(session.subscribe, session.status, session.status)
}

export function useErrorWords(): (error: unknown) => string {
  const { kind } = useSession()
  return (error) => errorWords(error, kind)
}
