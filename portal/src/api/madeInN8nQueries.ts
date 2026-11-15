import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { components } from './schema'

export type MadeInN8nView = components['schemas']['MadeInN8nView']

export const madeInN8nKey = (user: string) => ['made-in-n8n', user] as const

/** Workflows made in n8n that wait to be set up. Asked only for someone with n8n access, since the platform refuses everyone else. */
export function useMadeInN8n(enabled: boolean) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: madeInN8nKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/n8n/workflows')).workflows,
    enabled,
    retry: false,
  })
}

/** Registers one, then reads both lists again: it leaves this one and joins All workflows. */
export function useSetUpFromN8n() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (workflowId: string) => unwrap(await client.POST('/api/v1/use-cases/from-n8n', { body: { workflow_id: workflowId } })),
    onSettled: () => {
      for (const key of ['use-cases', 'made-in-n8n']) void queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
}
