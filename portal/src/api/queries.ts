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
  QuestionView,
  RefusalOut,
  SaveIn,
  ScheduleSaveIn,
  ToolList,
  WatchlistView,
} from './types'

export const POLL_MS = 3000

export const keys = {
  devUsers: () => ['dev-users'] as const,
  me: (user: string) => ['me', user] as const,
  runs: (user: string) => ['runs', user] as const,
  run: (user: string, runId: string) => ['run', user, runId] as const,
  useCases: (user: string) => ['use-cases', user] as const,
  useCase: (user: string, useCaseId: string) => ['use-case', user, useCaseId] as const,
  /** Under the workflow's own key, so whatever reads the workflow again reads this again too. */
  useCaseInN8n: (user: string, useCaseId: string) => ['use-case', user, useCaseId, 'n8n'] as const,
  /** Under the workflow's own key, so a workflow read again, as after a new schedule, reads its Check's try again too. */
  useCaseSimulation: (user: string, useCaseId: string) => ['use-case', user, useCaseId, 'simulation'] as const,
  /** One per event of the run, so each new event reads the blocks' states again. */
  runInN8n: (user: string, runId: string, seq: number) => ['run', user, runId, 'n8n', seq] as const,
  /** The latest run's events as the workflow page draws them on its steps, one per event of the run. */
  runFlow: (user: string, runId: string, seq: number) => ['run', user, runId, 'flow', seq] as const,
  versions: (user: string, useCaseId: string, version: number) => ['versions', user, useCaseId, version] as const,
  setUp: (user: string, useCaseId: string) => ['set-up', user, useCaseId] as const,
  made: (user: string, press: string) => ['set-up-made', user, press] as const,
  templates: () => ['templates'] as const,
  tools: () => ['tools'] as const,
  softwareFind: (user: string, name: string) => ['software-find', user, name] as const,
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
  /** How long a read stays fresh, so a window focus does not read it again. */
  staleTime?: number
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

export function useUseCases(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.useCases(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/use-cases')).use_cases,
    refetchInterval: pollEvery(options),
  })
}

export function useUseCase(useCaseId: string, enabled = true, options?: Pick<QueryOptions, 'poll'>) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.useCase(user, useCaseId),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/use-cases/{use_case_id}', { params: { path: { use_case_id: useCaseId } } })),
    enabled: enabled && useCaseId !== '',
    refetchInterval: pollEvery(options),
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

function useToolList<T>(select: (list: ToolList) => T) {
  const client = useApiClient()
  return useQuery({
    queryKey: keys.tools(),
    queryFn: async () => unwrap(await client.GET('/api/v1/tools')),
    staleTime: Infinity,
    select,
  })
}

export const useTools = () => useToolList((list) => list.tools)

/** The Jira projects the platform may write in, for the card's "Which Jira project should the ticket go in?". */
export const useJiraProjects = () => useToolList((list) => list.jira_projects)

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
  /** Only Do a test run sends it. */
  test?: boolean
}

export function useStartRun() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ useCaseId, idempotencyKey, test }: StartRunInput) =>
      unwrap(
        await client.POST('/api/v1/use-cases/{use_case_id}/runs', {
          params: { path: { use_case_id: useCaseId }, header: { 'Idempotency-Key': idempotencyKey } },
          ...(test ? { body: { test } } : {}),
        }),
      ),
    onSuccess: () => Promise.all(['runs', 'watchlist'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}

function decided(approval: ApprovalView | undefined): boolean {
  return approval !== undefined && approval.steps.every((step) => step.status === 'approved' || step.status === 'declined')
}

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
    ['approval', 'run', 'runs', 'home', 'teams-messages', 'jira-tickets', 'watchlist'].map((key) =>
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

/** The approval with this question in its place, so the thread shows it before the next read. */
export function withQuestion(approval: ApprovalView, question: QuestionView): ApprovalView {
  const known = approval.questions.some((kept) => kept.question_id === question.question_id)
  const questions = known ? approval.questions.map((kept) => (kept.question_id === question.question_id ? question : kept)) : [...approval.questions, question]
  return { ...approval, questions }
}

function useKeepQuestion(approvalId: string) {
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return {
    onSuccess: (question: QuestionView) => queryClient.setQueryData<ApprovalView>(keys.approval(user, approvalId), (old) => (old ? withQuestion(old, question) : old)),
    onSettled: () => Promise.all(['approval', 'home'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  }
}

export interface AskInput {
  readonly text: string
  readonly idempotencyKey: string
}

export function useAskQuestion(approvalId: string) {
  const client = useApiClient()
  return useMutation({
    mutationFn: async ({ text, idempotencyKey }: AskInput) =>
      unwrap(
        await client.POST('/api/v1/approvals/{approval_id}/questions', {
          params: { path: { approval_id: approvalId }, header: { 'Idempotency-Key': idempotencyKey } },
          body: { text },
        }),
      ),
    ...useKeepQuestion(approvalId),
  })
}

export interface AnswerInput {
  readonly questionId: string
  readonly text: string
}

export function useAnswerQuestion(approvalId: string) {
  const client = useApiClient()
  return useMutation({
    mutationFn: async ({ questionId, text }: AnswerInput) =>
      unwrap(
        await client.POST('/api/v1/approvals/{approval_id}/questions/{question_id}/answer', {
          params: { path: { approval_id: approvalId, question_id: questionId } },
          body: { text },
        }),
      ),
    ...useKeepQuestion(approvalId),
  })
}

/** The platform refused a Retry because the run had already left its stop: someone retried it first. */
export class RetriedFirst extends Error {
  /** Whose retry came after the run's newest stop, or null when the run names nobody, as when a retry started in n8n took it on. */
  readonly by: string | null

  constructor(by: string | null) {
    super('Someone retried the run first.')
    this.by = by
  }
}

export interface RetryAfter {
  readonly retried: () => void
  /** Called before the page reads the run again, which takes Retry away, so it runs even when Retry has already gone. */
  readonly retriedFirst: (by: string | null) => void
}

export function useRetry(runId: string, after: RetryAfter) {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      try {
        return unwrap(await client.POST('/api/v1/runs/{run_id}/retry', { params: { path: { run_id: runId } } }))
      } catch (error) {
        throw isConflict(error) ? await whyRetryConflicts(client, runId, error) : error
      }
    },
    onSuccess: after.retried,
    onError: (error) => {
      if (error instanceof RetriedFirst) after.retriedFirst(error.by)
    },
    onSettled: () => refreshAfterChange(queryClient),
  })
}

/**
 * A 409 means the run was not stopped any more, or that its stop can't be retried. Only the run says which. While it is still stopped,
 * or can't be read, the platform's own words stand.
 */
async function whyRetryConflicts(client: ApiClient, runId: string, refusal: unknown): Promise<unknown> {
  const [state, by] = await Promise.all([
    client.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } }).then(
      (answer) => unwrap(answer).state,
      () => null,
    ),
    retriedSinceTheStop(client, runId),
  ])
  return state === null || state === 'failed' ? refusal : new RetriedFirst(by)
}

async function retriedSinceTheStop(client: ApiClient, runId: string): Promise<string | null> {
  try {
    const { events } = await fetchEventPage(client, runId)
    const retried = events.slice(events.findLastIndex((event) => event.kind === 'run_failed') + 1).find((event) => event.kind === 'run_retried')
    return retried?.actor.kind === 'user' ? retried.actor.id : null
  } catch {
    return null
  }
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

export function invalidateAfterMarkDone(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(['jira-tickets', 'watchlist'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
}

/** Marks a practice Jira ticket Done. The watchlist then moves our version, so both refresh. */
export function useMarkDone() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (key: string) =>
      unwrap(await client.POST('/api/v1/mock-jira/tickets/{key}/done', { params: { path: { key } } })),
    onSettled: () => invalidateAfterMarkDone(queryClient),
  })
}

export function useWatchlist(options?: QueryOptions) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.watchlist(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/watchlist')).watchlist,
    refetchInterval: pollEvery(options),
    enabled: options?.enabled ?? true,
    ...(options?.staleTime === undefined ? {} : { staleTime: options.staleTime }),
  })
}

export function useFindSoftware() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (name: string) => unwrap(await client.POST('/api/v1/watchlist/find', { body: { name } })),
  })
}

/**
 * What the software finder says a plain name could mean, so the set-up card never asks the person to look a repository up. Only an
 * Operator may ask, and a name asked once is kept for the visit.
 */
export function useSoftwareFind(name: string | null, allowed: boolean) {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: keys.softwareFind(user, name ?? ''),
    queryFn: async () => unwrap(await client.POST('/api/v1/watchlist/find', { body: { name: name ?? '' } })),
    // Only an Operator may ask, so nobody else's card calls it.
    enabled: allowed && name !== null && name !== '',
    staleTime: Infinity,
    retry: false,
  })
}

/** A watched repository that moved or went missing is in Home's Needs you, so a change to the list reads Home again with the workflows. */
export function refreshAfterWatchlistChange(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(['use-cases', 'home'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
}

export function useAddSoftware() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (body: AddSoftware) => unwrap(await client.POST('/api/v1/watchlist/software', { body })),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.watchlist(user), view)
      return refreshAfterWatchlistChange(queryClient)
    },
  })
}

export function useRemoveSoftware() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  const rereadIfAlreadyRemoved = (error: Error) => (isNotFound(error) ? queryClient.invalidateQueries({ queryKey: keys.watchlist(user) }) : undefined)
  return useMutation({
    mutationFn: async (softwareId: string) =>
      unwrap(
        await client.DELETE('/api/v1/watchlist/software/{software_id}', { params: { path: { software_id: softwareId } } }),
      ),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.watchlist(user), view)
      return refreshAfterWatchlistChange(queryClient)
    },
    onError: rereadIfAlreadyRemoved,
  })
}

export function useRestoreSoftware() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (softwareId: string) =>
      unwrap(
        await client.POST('/api/v1/watchlist/software/{software_id}/restore', { params: { path: { software_id: softwareId } } }),
      ),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.watchlist(user), view)
      return refreshAfterWatchlistChange(queryClient)
    },
    onError: () => queryClient.invalidateQueries({ queryKey: keys.watchlist(user) }),
  })
}

function useSwitchAddress(tail: 'address' | 'address/undo') {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async ({ softwareId, repo }: { softwareId: string; repo: string }) =>
      unwrap(
        tail === 'address'
          ? await client.POST('/api/v1/watchlist/software/{software_id}/address', { params: { path: { software_id: softwareId } }, body: { repo } })
          : await client.POST('/api/v1/watchlist/software/{software_id}/address/undo', { params: { path: { software_id: softwareId } }, body: { repo } }),
      ),
    onSuccess: (view) => {
      queryClient.setQueryData(keys.watchlist(user), view)
      return refreshAfterWatchlistChange(queryClient)
    },
    onError: () => queryClient.invalidateQueries({ queryKey: keys.watchlist(user) }),
  })
}

/** Replaces the saved repository with the one GitHub reported. */
export function useUseNewAddress() {
  return useSwitchAddress('address')
}

export function usePutAddressBack() {
  return useSwitchAddress('address/undo')
}

/** A save from a version of the watchlist no longer in use is a 409 and saves nothing, so the watchlist is read again to show the new one. */
export function useSaveSchedule() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation({
    mutationFn: async (body: ScheduleSaveIn) => unwrap(await client.PUT('/api/v1/watchlist/schedule', { body })),
    onSuccess: (view) => queryClient.setQueryData(keys.watchlist(user), view),
    onError: () => void queryClient.invalidateQueries({ queryKey: keys.watchlist(user) }),
  })
}

/**
 * Turn off, from the version of the watchlist the page read. After a teammate's change since, it is a 409 and the schedule stays,
 * so the watchlist is read again to show it.
 */
export function turnOffScheduleOptions(client: ApiClient, queryClient: QueryClient, user: string) {
  return {
    mutationFn: async (expectedVersion: number) =>
      unwrap(await client.DELETE('/api/v1/watchlist/schedule', { params: { query: { expected_version: expectedVersion } } })),
    onSuccess: (view: WatchlistView) => queryClient.setQueryData(keys.watchlist(user), view),
    onError: () => void queryClient.invalidateQueries({ queryKey: keys.watchlist(user) }),
  }
}

export function useTurnOffSchedule() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  const user = useCacheScope()
  return useMutation(turnOffScheduleOptions(client, queryClient, user))
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

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/** Whether Settings has no working AI model. Unknown while it loads, so nothing is held back before we know. */
export function useModelOff(): boolean {
  const model = useModelSettings()
  return model.data !== undefined && model.data.active === null
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
  return Promise.all(
    ['model-settings', 'settings-history', 'confirmations'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
  )
}

const FORGET_THE_KEY = { gcTime: 0 } as const

export function useConnectModel() {
  const client = useApiClient()
  return useMutation({
    ...FORGET_THE_KEY,
    mutationFn: async (body: ConnectIn) => unwrap(await client.POST('/api/v1/settings/model/connect', { body })),
  })
}

export function useSaveModel() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    ...FORGET_THE_KEY,
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
