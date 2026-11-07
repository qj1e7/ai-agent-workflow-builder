import { useMutation, useQuery } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { PlannerAnswerIn } from './types'

export const CAPABILITIES_STALE_MS = 60_000

export const capabilitiesKey = (user: string) => ['capabilities', user] as const

/** What the platform can do, worked out by the platform. The Portal never decides a capability's state itself. */
export function useCapabilities({ enabled = true }: { enabled?: boolean } = {}) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: capabilitiesKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/capabilities')),
    staleTime: CAPABILITIES_STALE_MS,
    enabled,
  })
}

/** A mutation, not a query: an answer is not cached, and asking again with the same words is a new question. */
export function usePlannerAnswer() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (body: PlannerAnswerIn) => unwrap(await client.POST('/api/v1/planner/answer', { body })),
  })
}
