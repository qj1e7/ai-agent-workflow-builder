import { skipToken, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { unwrap, type ApiClient } from './client'
import { useApiClient, useCacheScope } from './context'
import { keys } from './queries'
import type { CreateAgentUseCase, ScheduleIn, UseCaseCreated, UseCaseView, VersionView, WatchlistView } from './types'

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

/** Saving makes the caller the schedule owner, which lifts a hold, and a new schedule publishes a new version. The view that comes back says both. */
export function saveScheduleOptions(client: ApiClient, queryClient: QueryClient, user: string, useCaseId: string) {
  return {
    mutationFn: async (body: ScheduleIn) =>
      unwrap(await client.PUT('/api/v1/use-cases/{use_case_id}/schedule', { params: { path: { use_case_id: useCaseId } }, body: { ...body, via: 'page' } })),
    onSuccess: (view: UseCaseView) => applySavedView(queryClient, user, view),
  }
}

/** The workflow and the list read again, so a card that changed it, or failed to, shows what the platform holds now. */
export function rereadChanged(queryClient: QueryClient, user: string, useCaseId: string): void {
  void queryClient.invalidateQueries({ queryKey: keys.useCase(user, useCaseId) })
  void queryClient.invalidateQueries({ queryKey: keys.useCases(user) })
}

interface ScheduleChange {
  readonly useCaseId: string
  readonly schedule: ScheduleIn
}

/** What a save from the chat answered: the workflow as it is now, and its newest version, which says who published it. */
export interface ChatSaved {
  readonly view: UseCaseView
  readonly newest: VersionView | undefined
}

/**
 * The edit card's Save: the page's route, marked as a change from the chat. The route answers with the running version even
 * when it published none, so the newest version is read too. A failed read leaves it unknown, and the save still stands.
 */
export function chatScheduleOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ useCaseId, schedule }: ScheduleChange): Promise<ChatSaved> => {
      const path = { params: { path: { use_case_id: useCaseId } } }
      const view = unwrap(await client.PUT('/api/v1/use-cases/{use_case_id}/schedule', { ...path, body: { ...schedule, via: 'chat' } }))
      const versions = await client.GET('/api/v1/use-cases/{use_case_id}/versions', path).catch(() => null)
      return { view, newest: versions?.data?.versions[0] }
    },
    onSuccess: ({ view }: ChatSaved) => applySavedView(queryClient, user, view),
    onSettled: (_saved: unknown, _error: unknown, { useCaseId }: ScheduleChange) => rereadChanged(queryClient, user, useCaseId),
  }
}

/** The edit card's Save for the Software watchlist, through the watchlist's own route, which keeps no versions. */
export function chatWatchlistOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ schedule }: ScheduleChange) => unwrap(await client.PUT('/api/v1/watchlist/schedule', { body: schedule })),
    onSuccess: (view: WatchlistView) => queryClient.setQueryData(keys.watchlist(user), view),
    onSettled: (_saved: unknown, _error: unknown, { useCaseId }: ScheduleChange) => rereadChanged(queryClient, user, useCaseId),
  }
}

/** The edit card's Undo: publishes the schedule from before `version` again. A later version makes it a 409, and nothing is published. */
export function undoOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ useCaseId, version }: { useCaseId: string; version: number }) =>
      unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/versions/{version}/undo', { params: { path: { use_case_id: useCaseId, version } }, body: { via: 'chat' } })),
    onSuccess: (view: UseCaseView) => applySavedView(queryClient, user, view),
    onSettled: (_view: unknown, _error: unknown, { useCaseId }: { useCaseId: string }) => rereadChanged(queryClient, user, useCaseId),
  }
}

export function useChatScheduleChange() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(chatScheduleOptions(client, queryClient, user))
}

export function useChatWatchlistSchedule() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(chatWatchlistOptions(client, queryClient, user))
}

export function useUndoVersion() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(undoOptions(client, queryClient, user))
}

export function useSaveWorkflowSchedule(useCaseId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(saveScheduleOptions(client, queryClient, user, useCaseId))
}

/** The versions of the workflow as it is at `version`, so a new version reads them again. A workflow at version 1 has no list to show, so nothing is read. */
export function useVersions(useCaseId: string, version: number) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.versions(user, useCaseId, version),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/use-cases/{use_case_id}/versions', { params: { path: { use_case_id: useCaseId } } })).versions,
    enabled: version > 1,
    placeholderData: (before) => before,
  })
}

/**
 * What Set up made, held for the set-up card and the build panel: the platform's answer with its build log and blocks, when it came,
 * which the log's replay counts from, and the test run the card started. Only the card writes it. The panel reads it.
 */
export interface SetUp {
  readonly created: UseCaseCreated
  readonly at: number
  readonly testRunId: string | null
}

export function holdSetUp(queryClient: QueryClient, user: string, created: UseCaseCreated, at: number): void {
  queryClient.setQueryData<SetUp>(keys.setUp(user, created.use_case_id), { created, at, testRunId: null })
}

export function testStarted(queryClient: QueryClient, user: string, useCaseId: string, runId: string): void {
  queryClient.setQueryData<SetUp>(keys.setUp(user, useCaseId), (held) => (held ? { ...held, testRunId: runId } : held))
}

/** Set up always makes a draft (ADR 0044): it never runs on its schedule, and only Turn it on publishes it. */
export function setUpOffOptions(client: ApiClient, queryClient: QueryClient, user: string, now: () => number = Date.now) {
  return {
    mutationFn: async (body: CreateAgentUseCase) => unwrap(await client.POST('/api/v1/agent-use-cases', { body: { ...body, on: false } })),
    onSuccess: (created: UseCaseCreated) => {
      holdSetUp(queryClient, user, created, now())
      rereadWorkflowsAndWatchlist(queryClient)
    },
  }
}

/** Turn it on publishes the draft. The card and the panel say On only from the view the platform answers with. */
export function turnOnOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async (useCaseId: string) => unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/turn-on', { params: { path: { use_case_id: useCaseId } } })),
    onSuccess: (view: UseCaseView) => applySavedView(queryClient, user, view),
  }
}

export function useSetUpOff() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(setUpOffOptions(client, queryClient, user))
}

export function useTurnOn() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(turnOnOptions(client, queryClient, user))
}

/** The set-up as the card holds it. Nothing is read from the platform: the build log comes only with Set up's answer. */
export function useSetUp(useCaseId: string): SetUp | undefined {
  const user = useCacheScope()
  return useQuery<SetUp>({ queryKey: keys.setUp(user, useCaseId), queryFn: skipToken, staleTime: Infinity, gcTime: Infinity }).data
}

export function useTestStarted(): (useCaseId: string, runId: string) => void {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return (useCaseId, runId) => testStarted(queryClient, user, useCaseId, runId)
}
