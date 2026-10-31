import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { unwrap, type ApiClient } from './client'
import { useApiClient, useCacheScope } from './context'
import { keys } from './queries'
import type { ScheduleIn, UseCaseView } from './types'

type Move = 'pause' | 'resume' | 'restore'

function post(client: ApiClient, move: Move, useCaseId: string) {
  const params = { params: { path: { use_case_id: useCaseId } } }
  switch (move) {
    case 'pause':
      return client.POST('/api/v1/use-cases/{use_case_id}/pause', params)
    case 'resume':
      return client.POST('/api/v1/use-cases/{use_case_id}/resume', params)
    case 'restore':
      return client.POST('/api/v1/use-cases/{use_case_id}/restore', params)
  }
}

const platformOrder = (a: UseCaseView, b: UseCaseView) => b.created_at.localeCompare(a.created_at) || b.use_case_id.localeCompare(a.use_case_id)

export function withView(list: readonly UseCaseView[], view: UseCaseView): UseCaseView[] {
  return [...list.filter((item) => item.use_case_id !== view.use_case_id), view].sort(platformOrder)
}

function changeList(queryClient: QueryClient, user: string, change: (list: UseCaseView[]) => UseCaseView[]): void {
  queryClient.setQueryData<UseCaseView[]>(keys.useCases(user), (list) => (list ? change(list) : list))
}

function rereadWorkflowsAndWatchlist(queryClient: QueryClient): void {
  for (const key of ['use-cases', 'watchlist']) void queryClient.invalidateQueries({ queryKey: [key] })
}

/** The view the platform answered a change with: held for the page, put in the list, and the lists read again. */
export function applySavedView(queryClient: QueryClient, user: string, view: UseCaseView): void {
  queryClient.setQueryData(keys.useCase(user, view.use_case_id), view)
  changeList(queryClient, user, (list) => withView(list, view))
  rereadWorkflowsAndWatchlist(queryClient)
}

function markStaleWithoutReading(queryClient: QueryClient, queryKey: readonly unknown[]): void {
  void queryClient.invalidateQueries({ queryKey, refetchType: 'none' })
}

export function useRereadWorkflow(): (useCaseId: string) => void {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return (useCaseId) => {
    void queryClient.invalidateQueries({ queryKey: keys.useCase(user, useCaseId) })
    rereadWorkflowsAndWatchlist(queryClient)
  }
}

export function useMoveWorkflow() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async ({ move, useCaseId }: { move: Move; useCaseId: string }) => unwrap(await post(client, move, useCaseId)),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.useCase(user, view.use_case_id), view)
      changeList(queryClient, user, (list) => withView(list, view))
      rereadWorkflowsAndWatchlist(queryClient)
    },
  })
}

export function useDeleteWorkflow() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (useCaseId: string) =>
      unwrap(await client.DELETE('/api/v1/use-cases/{use_case_id}', { params: { path: { use_case_id: useCaseId } } })),
    onSuccess: (deleted) => {
      changeList(queryClient, user, (list) => list.filter((item) => item.use_case_id !== deleted.use_case_id))
      markStaleWithoutReading(queryClient, keys.useCase(user, deleted.use_case_id))
      rereadWorkflowsAndWatchlist(queryClient)
    },
  })
}

/** Saving makes the caller the schedule owner, which lifts a hold. The view that comes back says so. */
export function useSaveWorkflowSchedule(useCaseId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (body: ScheduleIn) =>
      unwrap(await client.PUT('/api/v1/use-cases/{use_case_id}/schedule', { params: { path: { use_case_id: useCaseId } }, body })),
    onSuccess: (view) => applySavedView(queryClient, user, view),
  })
}
