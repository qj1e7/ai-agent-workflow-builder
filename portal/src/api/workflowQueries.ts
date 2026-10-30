import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { unwrap, type ApiClient } from './client'
import { useApiClient, useCacheScope } from './context'
import { keys } from './queries'
import type { UseCaseView } from './types'

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

/** The platform lists the newest first, so a workflow put back goes where the next read would place it. */
const platformOrder = (a: UseCaseView, b: UseCaseView) => b.created_at.localeCompare(a.created_at) || b.use_case_id.localeCompare(a.use_case_id)

export function withView(list: readonly UseCaseView[], view: UseCaseView): UseCaseView[] {
  return [...list.filter((item) => item.use_case_id !== view.use_case_id), view].sort(platformOrder)
}

function changeList(queryClient: QueryClient, user: string, change: (list: UseCaseView[]) => UseCaseView[]): void {
  queryClient.setQueryData<UseCaseView[]>(keys.useCases(user), (list) => (list ? change(list) : list))
}

/** The workflow and the watchlist both say whether it is paused, so both read again. */
function refresh(queryClient: QueryClient): void {
  for (const key of ['use-cases', 'watchlist']) void queryClient.invalidateQueries({ queryKey: [key] })
}

/** Pause, resume or put back a workflow. Each answers the workflow as it is now. */
export function useMoveWorkflow() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async ({ move, useCaseId }: { move: Move; useCaseId: string }) => unwrap(await post(client, move, useCaseId)),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.useCase(user, view.use_case_id), view)
      changeList(queryClient, user, (list) => withView(list, view))
      refresh(queryClient)
    },
  })
}

/** The page that pressed Delete is still open, so its own entry is only marked stale, not read again. */
export function useDeleteWorkflow() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (useCaseId: string) =>
      unwrap(await client.DELETE('/api/v1/use-cases/{use_case_id}', { params: { path: { use_case_id: useCaseId } } })),
    onSuccess: (deleted) => {
      changeList(queryClient, user, (list) => list.filter((item) => item.use_case_id !== deleted.use_case_id))
      void queryClient.invalidateQueries({ queryKey: keys.useCase(user, deleted.use_case_id), refetchType: 'none' })
      refresh(queryClient)
    },
  })
}
