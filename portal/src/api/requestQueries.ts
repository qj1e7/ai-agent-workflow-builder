import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { ReplyIn, TeamRequestView } from './types'

export const requestKey = (user: string, requestId: string) => ['team-request', user, requestId] as const

export function useTeamRequest(requestId: string) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: requestKey(user, requestId),
    queryFn: async () => unwrap(await client.GET('/api/v1/team-requests/{request_id}', { params: { path: { request_id: requestId } } })),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })
}

/** A reply changes Following up and, for the asker, Needs you, so Home is read again with the request. */
export function useReplyToRequest(requestId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (reply: ReplyIn) =>
      unwrap(await client.POST('/api/v1/team-requests/{request_id}/replies', { params: { path: { request_id: requestId } }, body: reply })),
    onSuccess: (view: TeamRequestView) => queryClient.setQueryData(requestKey(user, requestId), view),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['home'] }),
  })
}

/** The asker has read the replies up to `through`. Home is read again so the request leaves Needs you and the count drops. */
export function useMarkRequestSeen(requestId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (through: string) =>
      unwrap(await client.POST('/api/v1/team-requests/{request_id}/seen', { params: { path: { request_id: requestId } }, body: { through } })),
    onSuccess: (view: TeamRequestView) => queryClient.setQueryData(requestKey(user, requestId), view),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['home'] }),
  })
}
