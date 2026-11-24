import { useEffect } from 'react'
import { skipToken, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { unwrap, type ApiClient } from './client'
import { useApiClient, useCacheScope } from './context'
import { newIdempotencyKey } from './idempotency'
import { keys } from './queries'
import type { CreateAgentUseCase, RepublishIn, ScheduleIn, ScheduleSaveIn, UseCaseCreated, UseCaseView, VersionView, WatchlistView } from './types'

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

/**
 * Saving makes the caller the schedule owner, which lifts a hold, and a new schedule publishes a new version. The view that comes back
 * says both. A save from a version no longer in use is a 409, and nothing is saved.
 */
export function saveScheduleOptions(client: ApiClient, queryClient: QueryClient, user: string, useCaseId: string) {
  return {
    mutationFn: async (body: ScheduleSaveIn) =>
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
  /** The version the card read, so a save over a teammate's later change is refused. */
  readonly known: number
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
    mutationFn: async ({ useCaseId, schedule, known }: ScheduleChange): Promise<ChatSaved> => {
      const path = { params: { path: { use_case_id: useCaseId } } }
      const view = unwrap(await client.PUT('/api/v1/use-cases/{use_case_id}/schedule', { ...path, body: { ...schedule, via: 'chat', expected_version: known } }))
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
    mutationFn: async ({ schedule, known }: ScheduleChange) => unwrap(await client.PUT('/api/v1/watchlist/schedule', { body: { ...schedule, expected_version: known } })),
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

/** What a roll back or a put-back of the yes asks: who saw which version in use, and where in the Portal it was pressed. */
export interface Republish {
  readonly useCaseId: string
  readonly inUse: number
  readonly via: RepublishIn['via']
}

/** The workflow, its versions and Home read again, so every place that says what is in use says the new version. */
function rereadAfterRepublish(queryClient: QueryClient, user: string, useCaseId: string): void {
  void queryClient.invalidateQueries({ queryKey: keys.useCase(user, useCaseId) })
  void queryClient.invalidateQueries({ queryKey: ['versions', user, useCaseId] })
  void queryClient.invalidateQueries({ queryKey: ['home'] })
  void queryClient.invalidateQueries({ queryKey: keys.useCases(user) })
}

/** Rolls back to `version`: the platform publishes it again as a new version, and answers 409 when another version is in use by now. */
export function rollbackOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ useCaseId, version, inUse, via }: Republish & { version: number }) =>
      unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/versions/{version}/rollback', { params: { path: { use_case_id: useCaseId, version } }, body: { via, in_use: inUse } })),
    onSuccess: (view: UseCaseView) => applySavedView(queryClient, user, view),
    onSettled: (_view: unknown, _error: unknown, { useCaseId }: Republish) => rereadAfterRepublish(queryClient, user, useCaseId),
  }
}

/** Puts Ask for a yes back before each write, as a new version. */
export function addTheYesBackOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ useCaseId, inUse, via }: Republish) =>
      unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/add-the-yes-back', { params: { path: { use_case_id: useCaseId } }, body: { via, in_use: inUse } })),
    onSuccess: (view: UseCaseView) => applySavedView(queryClient, user, view),
    onSettled: (_view: unknown, _error: unknown, { useCaseId }: Republish) => rereadAfterRepublish(queryClient, user, useCaseId),
  }
}

export function useRollback() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(rollbackOptions(client, queryClient, user))
}

export function useAddTheYesBack() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(addTheYesBackOptions(client, queryClient, user))
}

/** Asks the platform to look in n8n now. The answer is never shown: a failure only means the minute's own sweep finds it. */
export async function sweepNow(client: ApiClient, queryClient: QueryClient, useCaseId?: string): Promise<void> {
  try {
    await client.POST('/api/v1/n8n/sweep', useCaseId === undefined ? {} : { params: { query: { use_case_id: useCaseId } } })
    void queryClient.invalidateQueries({ queryKey: ['home'] })
    if (useCaseId !== undefined) void queryClient.invalidateQueries({ queryKey: ['use-case'] })
  } catch {
    // The sweep runs every minute on its own.
  }
}

/**
 * For an Operator, looks in n8n when the window regains focus or the tab becomes visible, so a Changed in n8n card comes without
 * the minute's wait (ENGINE-PLAN 1, row 6). The platform looks at most once every few seconds, so a burst of focus events costs one look.
 */
export function useSweepOnFocus(enabled: boolean, useCaseId?: string): void {
  const client = useApiClient()
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    const look = () => {
      if (document.visibilityState === 'visible') void sweepNow(client, queryClient, useCaseId)
    }
    window.addEventListener('focus', look)
    document.addEventListener('visibilitychange', look)
    return () => {
      window.removeEventListener('focus', look)
      document.removeEventListener('visibilitychange', look)
    }
  }, [enabled, client, queryClient, useCaseId])
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

interface ExplainOptions {
  readonly version?: number | null
  readonly reworded?: boolean
  readonly enabled?: boolean
}

/** One version of a workflow, explained from the report the platform builds. A refusal (404, 409) carries words to show, so it is not tried again. */
export function useExplain(useCaseId: string, { version = null, reworded = false, enabled = true }: ExplainOptions = {}) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.explained(user, useCaseId, version, reworded),
    queryFn: async () =>
      unwrap(
        await client.GET('/api/v1/use-cases/{use_case_id}/explain', {
          params: { path: { use_case_id: useCaseId }, query: { ...(version === null ? {} : { version }), reworded } },
        }),
      ),
    enabled,
    staleTime: reworded ? 5 * 60_000 : 30_000,
    refetchOnWindowFocus: !reworded,
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
  /** The idempotency key the next test run asks with, kept here so a card drawn again asks with the same one. Test again makes a new one. */
  readonly testKey: string
  /** The key a start was last asked with, so no card asks twice with it. */
  readonly testAsked: string | null
}

export function holdSetUp(queryClient: QueryClient, user: string, created: UseCaseCreated, at: number, testKey: string): void {
  queryClient.setQueryData<SetUp>(keys.setUp(user, created.use_case_id), { created, at, testRunId: null, testKey, testAsked: null })
}

/**
 * Turn on for a draft the platform set up elsewhere, as a drafted workflow once an Approver checked it: held as a set-up with no build
 * log, so the set-up card's test run, and then on, follow as for any new workflow (ADR 0053, item 3).
 */
export function holdTurnOn(queryClient: QueryClient, user: string, useCaseId: string, at: number, testKey: string): void {
  holdSetUp(queryClient, user, { use_case_id: useCaseId, version: 1, build_log: [] }, at, testKey)
}

export function useHoldTurnOn(): (useCaseId: string) => void {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return (useCaseId) => holdTurnOn(queryClient, user, useCaseId, Date.now(), newIdempotencyKey())
}

const changeSetUp = (queryClient: QueryClient, user: string, useCaseId: string, change: Partial<SetUp>): void => {
  queryClient.setQueryData<SetUp>(keys.setUp(user, useCaseId), (held) => (held ? { ...held, ...change } : held))
}

export const testAsked = (queryClient: QueryClient, user: string, useCaseId: string, key: string): void => changeSetUp(queryClient, user, useCaseId, { testAsked: key })

export const testStarted = (queryClient: QueryClient, user: string, useCaseId: string, runId: string): void => changeSetUp(queryClient, user, useCaseId, { testRunId: runId })

export const testAgain = (queryClient: QueryClient, user: string, useCaseId: string, key: string): void => changeSetUp(queryClient, user, useCaseId, { testRunId: null, testKey: key })

/**
 * Starts a set-up's test run. The run the platform names is kept with the set-up here, in the mutation's own options, so it is kept even
 * when the card that asked was drawn away before the answer came.
 */
export function startTestOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async ({ useCaseId, key }: { useCaseId: string; key: string }) =>
      unwrap(
        await client.POST('/api/v1/use-cases/{use_case_id}/runs', {
          params: { path: { use_case_id: useCaseId }, header: { 'Idempotency-Key': key } },
          body: { test: true },
        }),
      ),
    onSuccess: (run: { readonly run_id: string }, { useCaseId }: { useCaseId: string }) => {
      testStarted(queryClient, user, useCaseId, run.run_id)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  }
}

export function useStartTest() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(startTestOptions(client, queryClient, user))
}

/** What one press of Set up came to: the workflow it made as a draft, or why the platform refused it. */
export type Made =
  | { readonly kind: 'built'; readonly useCaseId: string; readonly draftKept: boolean; readonly newAgents: readonly string[] }
  | { readonly kind: 'refused'; readonly said: readonly string[] }

/** Kept under the press's own key, so a card drawn again while the platform answered still settles. */
export function madeBySetUp(queryClient: QueryClient, user: string, press: string, made: Made): void {
  queryClient.setQueryData<Made>(keys.made(user, press), made)
}

export function useMadeBySetUp(press: string | null): { readonly made: Made | undefined; readonly keep: (press: string, made: Made) => void } {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  const made = useQuery<Made>({ queryKey: keys.made(user, press ?? ''), queryFn: skipToken, staleTime: Infinity, gcTime: Infinity, enabled: press !== null }).data
  return { made: press === null ? undefined : made, keep: (key, value) => madeBySetUp(queryClient, user, key, value) }
}

/** Set up always makes a draft (ADR 0044): it never runs on its schedule, and only Turn it on publishes it. */
export function setUpOffOptions(client: ApiClient, queryClient: QueryClient, user: string, now: () => number = Date.now, key: () => string = newIdempotencyKey) {
  return {
    mutationFn: async (body: CreateAgentUseCase) => unwrap(await client.POST('/api/v1/agent-use-cases', { body: { ...body, on: false } })),
    onSuccess: (created: UseCaseCreated) => {
      holdSetUp(queryClient, user, created, now(), key())
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

/** What the card writes to its set-up about the test run: the key it asked with, the run the platform named, and a new key for Test again. */
export function useTestRunMarks() {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return {
    asked: (useCaseId: string, key: string) => testAsked(queryClient, user, useCaseId, key),
    started: (useCaseId: string, runId: string) => testStarted(queryClient, user, useCaseId, runId),
    again: (useCaseId: string) => testAgain(queryClient, user, useCaseId, newIdempotencyKey()),
  }
}

export async function sendOpenInN8n(client: ApiClient, useCaseId: string) {
  return unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/open-in-n8n', { params: { path: { use_case_id: useCaseId } } }))
}

/** Moves the workflow to the person's own n8n space. The workflow, and so who holds it, is read again either way. */
export function useOpenInN8n() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: (useCaseId: string) => sendOpenInN8n(client, useCaseId),
    onSettled: (_held, _error, useCaseId) => {
      void queryClient.invalidateQueries({ queryKey: keys.useCase(user, useCaseId) })
      rereadWorkflowsAndWatchlist(queryClient)
    },
  })
}

/** Moves the workflow back to the platform's n8n project, from whoever holds it. */
export function useTakeBack() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (useCaseId: string) =>
      unwrap(await client.POST('/api/v1/use-cases/{use_case_id}/take-back', { params: { path: { use_case_id: useCaseId } } })),
    onSettled: (_free, _error, useCaseId) => {
      void queryClient.invalidateQueries({ queryKey: keys.useCase(user, useCaseId) })
      rereadWorkflowsAndWatchlist(queryClient)
    },
  })
}

/** The workflow as n8n holds it, with who holds it now. Only people with n8n access may read it. */
export function useUseCaseInN8n(useCaseId: string, { enabled, poll }: { readonly enabled: boolean; readonly poll?: number }) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.useCaseInN8n(user, useCaseId),
    queryFn: async () => unwrap(await client.GET('/api/v1/use-cases/{use_case_id}/n8n', { params: { path: { use_case_id: useCaseId } } })),
    enabled,
    refetchInterval: poll ?? false,
  })
}

/** n8n's own record of an ended run can come a moment after the run's last event, so it is asked for a few times more. */
const RECORD_TRIES = 5
const RECORD_EVERY_MS = 3_000

/** A run as n8n carried it: read again at each new event of the run, keeping the last answer on screen meanwhile. */
export function useRunInN8n(runId: string, seq: number, ended: boolean) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.runInN8n(user, runId, seq),
    queryFn: async () => unwrap(await client.GET('/api/v1/runs/{run_id}/n8n', { params: { path: { run_id: runId } } })),
    placeholderData: (before) => before,
    refetchInterval: (query) => (ended && query.state.data?.from_n8n === false && query.state.dataUpdateCount < RECORD_TRIES ? RECORD_EVERY_MS : false),
  })
}

/** Asks the platform to look in n8n for this workflow now, once, as its In n8n tab opens (ENGINE-PLAN section 1, row 5). */
export function useSweepOnOpen(useCaseId: string): void {
  const client = useApiClient()
  const queryClient = useQueryClient()
  useEffect(() => {
    void sweepNow(client, queryClient, useCaseId)
  }, [client, queryClient, useCaseId])
}
