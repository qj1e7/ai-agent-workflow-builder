import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { DraftIn, PlanOut } from './types'

export const draftsKey = (user: string) => ['drafts', user] as const

export function useUnderstand() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (text: string) => unwrap(await client.POST('/api/v1/builder/understand', { body: { text } })),
  })
}

export function usePlanFor(task: string, enabled: boolean, planned: PlanOut | undefined) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: ['plan', user, task] as const,
    queryFn: async () => unwrap(await client.POST('/api/v1/builder/plan', { body: { task } })),
    enabled: enabled && task !== '',
    staleTime: Infinity,
    retry: false,
    initialData: planned,
  })
}

export function useDrafts(enabled: boolean) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: draftsKey(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/drafts')).drafts,
    enabled,
  })
}

function rereadDrafts(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([queryClient.invalidateQueries({ queryKey: ['home'] }), queryClient.invalidateQueries({ queryKey: ['drafts'], refetchType: 'none' })])
}

export function useSaveDraft() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ draftId, draft }: { draftId: string; draft: DraftIn }) =>
      unwrap(await client.PUT('/api/v1/drafts/{draft_id}', { params: { path: { draft_id: draftId } }, body: draft })),
    onSettled: () => rereadDrafts(queryClient),
  })
}

export function useDeleteDraft() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (draftId: string) => {
      const { response, error } = await client.DELETE('/api/v1/drafts/{draft_id}', { params: { path: { draft_id: draftId } } })
      if (!response.ok && response.status !== 404) throw new ApiError(response.status, error)
    },
    onSettled: () => rereadDrafts(queryClient),
  })
}

export function refusedWords(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return []
  const body = error.body as { detail?: unknown; problems?: unknown } | null
  const list = Array.isArray(body?.detail) ? body.detail : Array.isArray(body?.problems) ? body.problems : []
  return list.flatMap((item: unknown) => {
    const said = item as { msg?: unknown; message?: unknown; loc?: unknown } | null
    const words = said?.msg ?? said?.message
    if (typeof words !== 'string') return []
    const loc = Array.isArray(said?.loc) ? (said.loc as unknown[]) : []
    const input = loc.at(-2) === 'values' ? loc.at(-1) : undefined
    return [typeof input === 'string' ? `${input}: ${words}` : words]
  })
}
