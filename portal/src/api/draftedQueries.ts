import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { DraftAnswerIn, DraftedWorkflowView, SetUpApprovalView, SetUpDecisionIn } from './types'

export const DRAFTED_POLL_MS = 2000

export const draftedKey = (user: string, draftedId: string) => ['drafted', user, draftedId] as const
export const setUpApprovalKey = (user: string, approvalId: string) => ['setup-approval', user, approvalId] as const

/** True while the platform moves a drafted workflow on its own: the drafter works, a yes is awaited, or n8n is taking it. */
export function stillMoving(view: Pick<DraftedWorkflowView, 'state' | 'set_up'> | undefined): boolean {
  if (view === undefined) return false
  if (view.state === 'drafting' || view.state === 'waiting') return true
  return view.state === 'approved' && (view.set_up === null || view.set_up.state === 'setting_up')
}

/** A drafted workflow as it stands now: the newest revision, read again every couple of seconds while it still moves. */
export function useDrafted(draftedId: string) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: draftedKey(user, draftedId),
    queryFn: async () => unwrap(await client.GET('/api/v1/drafted-workflows/{drafted_id}', { params: { path: { drafted_id: draftedId } } })),
    refetchInterval: (query) => (stillMoving(query.state.data) ? DRAFTED_POLL_MS : false),
    enabled: draftedId !== '',
  })
}

function useRereadDrafted() {
  const queryClient = useQueryClient()
  return () => Promise.all(['drafted', 'setup-approval', 'use-cases', 'home', 'teams-messages'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
}

/** What a change, a send or a set-up answered is the drafted workflow now, so its cards show it before the next read. */
function useKeepDrafted() {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return (view: DraftedWorkflowView) => queryClient.setQueryData(draftedKey(user, view.drafted_id), view)
}

export interface StartDrafting {
  readonly words: string
  readonly idempotencyKey: string
}

/** Starts the drafter on words, unchanged. The same key answers the drafted workflow it started. */
export function useStartDrafting() {
  const client = useApiClient()
  const reread = useRereadDrafted()
  return useMutation({
    mutationFn: async ({ words, idempotencyKey }: StartDrafting) =>
      unwrap(await client.POST('/api/v1/drafted-workflows', { params: { header: { 'Idempotency-Key': idempotencyKey } }, body: { words } })),
    onSettled: reread,
  })
}

export interface ChangeDrafted {
  readonly draftedId: string
  readonly words: string
  readonly revision: number
}

/** Asks for a change to the newest revision. The next revision comes back drafting. A 409 carries words to show. */
export function useChangeDrafted() {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async ({ draftedId, words, revision }: ChangeDrafted) =>
      unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/changes', { params: { path: { drafted_id: draftedId } }, body: { words, revision } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

export function useSendDrafted(draftedId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async (revision: number) => unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/send', { params: { path: { drafted_id: draftedId } }, body: { revision } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

/** Answers one setting of a drafted workflow. The answer makes a new revision, which stays on the same card. A 409 carries words to show. */
export function useAnswerDrafted(draftedId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async (body: DraftAnswerIn) => unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/answers', { params: { path: { drafted_id: draftedId } }, body })),
    onSuccess: keep,
    onSettled: reread,
  })
}

/** Opens the newest revision in the Operator's own n8n space. */
export function useEditInN8n(draftedId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async (revision: number) => unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/n8n', { params: { path: { drafted_id: draftedId } }, body: { revision } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

/** Reads what was edited in n8n back as a new revision. */
export function useDoneInN8n(draftedId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async () => unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/n8n/done', { params: { path: { drafted_id: draftedId } } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

/** Tries a set-up that n8n didn't take again. */
export function useSetUpAgain(draftedId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  const keep = useKeepDrafted()
  return useMutation({
    mutationFn: async () => unwrap(await client.POST('/api/v1/drafted-workflows/{drafted_id}/set-up', { params: { path: { drafted_id: draftedId } } })),
    onSuccess: keep,
    onSettled: reread,
  })
}

function setUpMoving(view: SetUpApprovalView | undefined): boolean {
  return view !== undefined && view.approval.status === 'approved' && (view.set_up === null || view.set_up.state === 'setting_up')
}

/** A set-up approval as its page shows it, read again while the set-up after a yes is still going. */
export function useSetUpApproval(approvalId: string) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: setUpApprovalKey(user, approvalId),
    queryFn: async () => unwrap(await client.GET('/api/v1/setup-approvals/{approval_id}', { params: { path: { approval_id: approvalId } } })),
    refetchInterval: (query) => (setUpMoving(query.state.data) ? DRAFTED_POLL_MS : false),
    enabled: approvalId !== '',
  })
}

export function useDecideSetUp(approvalId: string) {
  const client = useApiClient()
  const reread = useRereadDrafted()
  return useMutation({
    mutationFn: async (body: SetUpDecisionIn) => unwrap(await client.POST('/api/v1/setup-approvals/{approval_id}/decisions', { params: { path: { approval_id: approvalId } }, body })),
    onSettled: reread,
  })
}
