import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { ConnectionId } from './types'

export const capabilitiesKey = (user: string) => ['capabilities', user] as const
export const connectionsKey = (user: string) => ['connections', user] as const

/** The one registry of what the platform can do. Every screen reads each capability's state from here. */
export function useCapabilities() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: capabilitiesKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/capabilities')),
  })
}

export function useConnections() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: connectionsKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/settings/connections')),
  })
}

/** A check only reads the system. What it found changes the connection, what depends on it, and Home's Needs you, so all are read again. */
export function useCheckConnection(connectionId: ConnectionId) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(await client.POST('/api/v1/settings/connections/{connection}/check', { params: { path: { connection: connectionId } } })),
    onSettled: () => Promise.all(['connections', 'capabilities', 'home'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}
