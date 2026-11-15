import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { CheckPartIn, DraftIn, PlanOut, PlannerAnswerIn } from './types'
import { useRereadWorkflow } from './workflowQueries'

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
  const reread = useRereadWorkflow()
  return useMutation({
    mutationFn: async (body: PlannerAnswerIn) => unwrap(await client.POST('/api/v1/planner/answer', { body })),
    // A pause or a resume answer is the one answer that changed a workflow, so its views are read again.
    onSuccess: (reply) => {
      if ((reply.answer === 'pause' || reply.answer === 'resume') && reply.use_case_id !== null) reread(reply.use_case_id)
    },
  })
}

/** The Planner’s check of one part the person changed, so a change can’t bring in something the platform can’t do. */
export function useCheckPart() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (body: CheckPartIn) => unwrap(await client.POST('/api/v1/planner/check-part', { body })),
  })
}

export const draftsKey = (user: string) => ['drafts', user] as const

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

export function useReadAgentCards() {
  const client = useApiClient()
  return async () => unwrap(await client.GET('/api/v1/agent-cards')).cards
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
