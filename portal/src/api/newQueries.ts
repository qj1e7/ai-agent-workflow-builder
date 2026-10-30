import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { DraftIn, PlanOut } from './types'

export const draftsKey = (user: string) => ['drafts', user] as const

/** What the Planner understood of a task. Nothing is saved. */
export function useUnderstand() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (text: string) => unwrap(await client.POST('/api/v1/builder/understand', { body: { text } })),
  })
}

/** The Planner's plan for the rows. The task is the key, so the same rows are planned once. */
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
  return Promise.all(['home', 'drafts'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
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
      // The platform answers 204 with no body, so there is no data to unwrap.
      const { response, error } = await client.DELETE('/api/v1/drafts/{draft_id}', { params: { path: { draft_id: draftId } } })
      if (!response.ok && response.status !== 404) throw new ApiError(response.status, error)
    },
    onSettled: () => rereadDrafts(queryClient),
  })
}

/** The messages in a 422 answer: FastAPI's list of {msg}, or a card's {problems: [{message}]}. */
export function refusedWords(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return []
  const body = error.body as { detail?: unknown; problems?: unknown } | null
  const list = Array.isArray(body?.detail) ? body.detail : Array.isArray(body?.problems) ? body.problems : []
  return list.flatMap((item: unknown) => {
    const said = item as { msg?: unknown; message?: unknown } | null
    const words = said?.msg ?? said?.message
    return typeof words === 'string' ? [words] : []
  })
}
