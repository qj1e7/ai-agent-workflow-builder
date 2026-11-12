import { useQuery } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { DecidedReply } from './types'

export const HOME_REFRESH_MS = 15_000

export const homeKey = (user: string) => ['home', user] as const

export function useHome({ enabled = true }: { enabled?: boolean } = {}) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: homeKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/home')),
    refetchInterval: HOME_REFRESH_MS,
    enabled,
  })
}

/** The signed-in person's own decisions, newest first. `verdict` keeps only approvals or only declines. */
export function useDecisions(verdict: DecidedReply['only']) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: ['decisions', user, verdict] as const,
    queryFn: async () => unwrap(await client.GET('/api/v1/decisions', { params: { query: verdict === null ? {} : { verdict } } })),
  })
}
