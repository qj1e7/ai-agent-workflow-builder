import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { FixView } from './types'

export const FIX_POLL_MS = 3000

export const fixKey = (user: string, fixId: string) => ['fix', user, fixId] as const

/** True while the platform still moves a fix on its own: it drafts, an Approver's yes is awaited, or its test run goes. */
export function fixMoving(view: Pick<FixView, 'state'> | undefined): boolean {
  return view !== undefined && (view.state === 'drafting' || view.state === 'waiting' || view.state === 'testing')
}

/** A fix as the platform says it stands, read again every few seconds while it still moves. Off until there is a fix. */
export function useFix(fixId: string | null) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: fixKey(user, fixId ?? ''),
    queryFn: async () => unwrap(await client.GET('/api/v1/fixes/{fix_id}', { params: { path: { fix_id: fixId ?? '' } } })),
    refetchInterval: (query) => (fixMoving(query.state.data) ? FIX_POLL_MS : false),
    enabled: fixId !== null,
  })
}

function useKeepFix() {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return {
    keep: (view: FixView) => queryClient.setQueryData(fixKey(user, view.fix_id), view),
    reread: () => Promise.all(['fix', 'run', 'home', 'troubleshooting'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  }
}

/** Asks for a fix on a stopped run. The platform answers at once, while the fix drafts. */
export function useStartFix(runId: string) {
  const client = useApiClient()
  const { keep, reread } = useKeepFix()
  return useMutation({
    mutationFn: async () => unwrap(await client.POST('/api/v1/runs/{run_id}/fixes', { params: { path: { run_id: runId } } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

/** Only after an Approver's yes: the one real test run, which writes nothing, and then on if it passed. */
export function useTurnBackOn(fixId: string) {
  const client = useApiClient()
  const { keep, reread } = useKeepFix()
  return useMutation({
    mutationFn: async () => unwrap(await client.POST('/api/v1/fixes/{fix_id}/turn-back-on', { params: { path: { fix_id: fixId } } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

export interface FixAnswer {
  readonly setting: string
  readonly choice?: string
  readonly typed?: string
}

/** The answer to the one setting a handed-back fix asks for. It needs the same yes and the same test run. */
export function useAnswerFix(fixId: string) {
  const client = useApiClient()
  const { keep, reread } = useKeepFix()
  return useMutation({
    mutationFn: async (body: FixAnswer) => unwrap(await client.POST('/api/v1/fixes/{fix_id}/answers', { params: { path: { fix_id: fixId } }, body })),
    onSuccess: keep,
    onSettled: reread,
  })
}
