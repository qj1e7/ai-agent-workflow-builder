import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { createApiClient, type ApiClient } from './client'
import { wallClock, type RunClock } from './clock'
import type { PortalMode } from './config'
import { getDevUser } from './session'

export interface ApiEnvironment {
  readonly mode: PortalMode
  readonly fetch: typeof fetch
  readonly client: ApiClient
  readonly clock: RunClock
}

const ApiContext = createContext<ApiEnvironment | null>(null)

interface ApiProviderProps {
  mode: PortalMode
  fetch: typeof fetch
  clock?: RunClock
  baseUrl?: string
  children: ReactNode
}

export function ApiProvider({ mode, fetch: fetchImpl, clock = wallClock, baseUrl, children }: ApiProviderProps) {
  const value = useMemo<ApiEnvironment>(
    () => ({ mode, fetch: fetchImpl, clock, client: createApiClient(fetchImpl, getDevUser, baseUrl) }),
    [mode, fetchImpl, clock, baseUrl],
  )
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
