import { keepPreviousData, queryOptions, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, unwrap, type ApiClient } from './client'
import { useApiClient, useSession, useCacheScope } from './context'
import type {
  AddSoftware,
  AddressDecisionIn,
  ApprovalView,
  CardDefinition,
  ConnectIn,
  CreateAgentUseCase,
  CreateUseCase,
  DecisionIn,
  EventPage,
  RefusalOut,
  SaveIn,
  ScheduleIn,
} from './types'

export const POLL_MS = 3000

export const keys = {
  devUsers: () => ['dev-users'] as const,
  me: (user: string) => ['me', user] as const,
  runs: (user: string) => ['runs', user] as const,
  run: (user: string, runId: string) => ['run', user, runId] as const,
  useCases: (user: string) => ['use-cases', user] as const,
  useCase: (user: string, useCaseId: string) => ['use-case', user, useCaseId] as const,
  templates: () => ['templates'] as const,
  tools: () => ['tools'] as const,
  agentCards: (user: string) => ['agent-cards', user] as const,
  approval: (user: string, approvalId: string) => ['approval', user, approvalId] as const,
  troubleshoot: (user: string, runId: string, attempt: number) => ['troubleshoot', user, runId, attempt] as const,
  teamsMessages: (user: string) => ['teams-messages', user] as const,
  jiraTickets: (user: string) => ['jira-tickets', user] as const,
  modelSettings: (user: string) => ['model-settings', user] as const,
  watchlist: (user: string) => ['watchlist', user] as const,
}

interface QueryOptions {
  /** true polls every POLL_MS; a number polls that often. */
  poll?: boolean | number
  enabled?: boolean
}

function pollEvery(options: QueryOptions | undefined): number | false {
  if (typeof options?.poll === 'number') return options.poll
  return options?.poll ? POLL_MS : false
}

export function useDevUsers() {
  const client = useApiClient()
  const { kind } = useSession()
  return useQuery({
    queryKey: keys.devUsers(),
    queryFn: async () => unwrap(await client.GET('/api/v1/dev/users')).users,
    staleTime: Infinity,
    enabled: kind === 'dev',
  })
}

export function useMe(enabled = true) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.me(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/me')),
    staleTime: 60_000,
    enabled,
  })
}

export function useRuns(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.runs(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/runs')).runs,
    refetchInterval: pollEvery(options),
    enabled: options?.enabled ?? true,
  })
}

export function useRun(runId: string, options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.run(user, runId),
    queryFn: async () => unwrap(await client.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } })),
    refetchInterval: pollEvery(options),
    enabled: runId !== '',
  })
}

export function useUseCases() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.useCases(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/use-cases')).use_cases,
  })
}

export function useUseCase(useCaseId: string, enabled = true) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.useCase(user, useCaseId),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/use-cases/{use_case_id}', { params: { path: { use_case_id: useCaseId } } })),
    enabled: enabled && useCaseId !== '',
  })
}

export function useTemplates() {
  const client = useApiClient()
  return useQuery({
    queryKey: keys.templates(),
    queryFn: async () => unwrap(await client.GET('/api/v1/templates')).templates,
    staleTime: Infinity,
  })
}

export function useTools() {
  const client = useApiClient()
  return useQuery({
    queryKey: keys.tools(),
    queryFn: async () => unwrap(await client.GET('/api/v1/tools')).tools,
    staleTime: Infinity,
  })
}

export function useAgentCards() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.agentCards(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/agent-cards')).cards,
  })
}

/** The Planner's plan for a task. The platform answers 409 until an AI model is connected. */
export function usePlan() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (task: string) => unwrap(await client.POST('/api/v1/builder/plan', { body: { task } })),
  })
}

/** Checks a card as it is written. The key is the card itself, so the same card is never checked twice. */
export function useCheckCard(card: CardDefinition | null) {
  const client = useApiClient()
  return useQuery({
    queryKey: ['card-check', card] as const,
    queryFn: async () => unwrap(await client.POST('/api/v1/agent-cards/check', { body: card as CardDefinition })),
    enabled: card !== null,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  })
}

interface SaveCardInput {
  /** The card to write a next version of, or null for a new card. */
  cardId: string | null
  card: CardDefinition
}

export function useSaveCard() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ cardId, card }: SaveCardInput) =>
      cardId === null
        ? unwrap(await client.POST('/api/v1/agent-cards', { body: card }))
        : unwrap(await client.PUT('/api/v1/agent-cards/{card_id}', { params: { path: { card_id: cardId } }, body: card })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-cards'] }),
  })
}

export function useCreateAgentUseCase() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateAgentUseCase) => unwrap(await client.POST('/api/v1/agent-use-cases', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['use-cases'] }),
  })
}

export function useCreateUseCase() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateUseCase) => unwrap(await client.POST('/api/v1/use-cases', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['use-cases'] }),
  })
}

interface StartRunInput {
  useCaseId: string
  idempotencyKey: string
}

export function useStartRun() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ useCaseId, idempotencyKey }: StartRunInput) =>
      unwrap(
        await client.POST('/api/v1/use-cases/{use_case_id}/runs', {
          params: { path: { use_case_id: useCaseId }, header: { 'Idempotency-Key': idempotencyKey } },
        }),
      ),
    onSuccess: () => Promise.all(['runs', 'watchlist'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}

function decided(approval: ApprovalView | undefined): boolean {
  return approval !== undefined && approval.steps.every((step) => step.status === 'approved' || step.status === 'declined')
}

/** One approval. It stops polling once every step is decided. */
export function approvalQuery(client: ApiClient, user: string, approvalId: string, options?: QueryOptions) {
  return queryOptions({
    queryKey: keys.approval(user, approvalId),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/approvals/{approval_id}', { params: { path: { approval_id: approvalId } } })),
    refetchInterval: (query) => (decided(query.state.data) ? false : pollEvery(options)),
    enabled: options?.enabled ?? true,
  })
}

export function useApproval(approvalId: string, options?: QueryOptions) {
  return useQuery(approvalQuery(useApiClient(), useCacheScope(), approvalId, options))
}

/** The same cache entries as useApproval, one per id. */
export function useApprovals(approvalIds: readonly string[], options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQueries({ queries: approvalIds.map((approvalId) => approvalQuery(client, user, approvalId, options)) })
}

function refreshAfterChange(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(
    ['approval', 'run', 'runs', 'teams-messages', 'jira-tickets', 'watchlist'].map((key) =>
      queryClient.invalidateQueries({ queryKey: [key] }),
    ),
  )
}

export function useDecide(approvalId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: DecisionIn) =>
      unwrap(
        await client.POST('/api/v1/approvals/{approval_id}/decisions', {
          params: { path: { approval_id: approvalId } },
          body,
        }),
      ),
    onSettled: () => refreshAfterChange(queryClient),
  })
}

export function useRetry(runId: string) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(await client.POST('/api/v1/runs/{run_id}/retry', { params: { path: { run_id: runId } } })),
    onSettled: () => refreshAfterChange(queryClient),
  })
}

/** Keyed by attempt, so a second failure never shows the first one's cached advice. */
export function useTroubleshoot(runId: string, enabled: boolean, attempt: number) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.troubleshoot(user, runId, attempt),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/runs/{run_id}/troubleshoot', { params: { path: { run_id: runId } } })),
    enabled,
  })
}

export function useTeamsMessages(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.teamsMessages(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/teams-stub/messages')).messages,
    refetchInterval: pollEvery(options),
    enabled: options?.enabled ?? true,
  })
}

export function useMockJiraTickets(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.jiraTickets(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/mock-jira/tickets')).tickets,
    refetchInterval: pollEvery(options),
  })
}

/** Marks a practice Jira ticket Done. The watchlist then moves our version, so both refresh. */
export function useMarkDone() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (key: string) =>
      unwrap(await client.POST('/api/v1/mock-jira/tickets/{key}/done', { params: { path: { key } } })),
    onSettled: () =>
      Promise.all(['jira-tickets', 'watchlist'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}

export function useWatchlist(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.watchlist(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/watchlist')).watchlist,
    refetchInterval: pollEvery(options),
  })
}

export function useAddSoftware() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (body: AddSoftware) => unwrap(await client.POST('/api/v1/watchlist/software', { body })),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.watchlist(user), view)
      return queryClient.invalidateQueries({ queryKey: ['use-cases'] })
    },
  })
}

export function useRemoveSoftware() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (softwareId: string) =>
      unwrap(
        await client.DELETE('/api/v1/watchlist/software/{software_id}', { params: { path: { software_id: softwareId } } }),
      ),
    onSuccess: (view) => queryClient.setQueryData(keys.watchlist(user), view),
  })
}

export function useSaveSchedule() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (body: ScheduleIn) => unwrap(await client.PUT('/api/v1/watchlist/schedule', { body })),
    onSuccess: (view) => queryClient.setQueryData(keys.watchlist(user), view),
  })
}

export function useTurnOffSchedule() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async () => unwrap(await client.DELETE('/api/v1/watchlist/schedule')),
    onSuccess: (view) => queryClient.setQueryData(keys.watchlist(user), view),
  })
}

export async function fetchEventPage(client: ApiClient, runId: string, after = 0): Promise<EventPage> {
  const page = unwrap(
    await client.GET('/api/v1/runs/{run_id}/events', {
      params: { path: { run_id: runId }, query: { after }, header: { accept: 'application/json' } },
    }),
  )
  if (typeof page === 'string') throw new ApiError(200, 'The platform answered with a stream instead of a page.')
  return page
}

export function refusalOf(error: unknown): RefusalOut | null {
  if (!(error instanceof ApiError) || error.status !== 403) return null
  const body = error.body as Partial<RefusalOut> | null
  return typeof body?.refusal === 'string' && typeof body.message === 'string'
    ? { refusal: body.refusal, message: body.message }
    : null
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409
}

export function useModelSettings() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.modelSettings(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/settings/model')),
  })
}

function refreshModelSettings(queryClient: QueryClient): Promise<unknown> {
  return queryClient.invalidateQueries({ queryKey: ['model-settings'] })
}

export function useConnectModel() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (body: ConnectIn) => unwrap(await client.POST('/api/v1/settings/model/connect', { body })),
  })
}

export function useSaveModel() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: SaveIn) => unwrap(await client.PUT('/api/v1/settings/model', { body })),
    onSettled: () => refreshModelSettings(queryClient),
  })
}

export function useTurnModelOff() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      // The platform answers 204 with no body, so there is no data to unwrap.
      const { response, error } = await client.DELETE('/api/v1/settings/model')
      if (!response.ok) throw new ApiError(response.status, error)
    },
    onSettled: () => refreshModelSettings(queryClient),
  })
}

export function useDecideAddress() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: AddressDecisionIn) =>
      unwrap(await client.POST('/api/v1/settings/model/address-decision', { body })),
    onSettled: () => refreshModelSettings(queryClient),
  })
}
