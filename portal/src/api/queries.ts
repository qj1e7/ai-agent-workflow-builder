import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, unwrap, type ApiClient } from './client'
import { useApiClient } from './context'
import { useDevUser } from './session'
import type { CreateUseCase, DecisionIn, EventPage, RefusalOut } from './types'

export const POLL_MS = 3000

export const keys = {
  devUsers: () => ['dev-users'] as const,
  runs: (user: string) => ['runs', user] as const,
  run: (user: string, runId: string) => ['run', user, runId] as const,
  useCases: (user: string) => ['use-cases', user] as const,
  useCase: (user: string, useCaseId: string) => ['use-case', user, useCaseId] as const,
  templates: () => ['templates'] as const,
  approval: (user: string, approvalId: string) => ['approval', user, approvalId] as const,
  troubleshoot: (user: string, runId: string) => ['troubleshoot', user, runId] as const,
  teamsMessages: (user: string) => ['teams-messages', user] as const,
  jiraTickets: (user: string) => ['jira-tickets', user] as const,
}

interface QueryOptions {
  poll?: boolean
}

function pollEvery(options: QueryOptions | undefined): number | false {
  return options?.poll ? POLL_MS : false
}

export function useDevUsers() {
  const client = useApiClient()
  return useQuery({
    queryKey: keys.devUsers(),
    queryFn: async () => unwrap(await client.GET('/api/v1/dev/users')).users,
    staleTime: Infinity,
  })
}

export function useRuns(options?: QueryOptions) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.runs(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/runs')).runs,
    refetchInterval: pollEvery(options),
  })
}

export function useRun(runId: string, options?: QueryOptions) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.run(user, runId),
    queryFn: async () => unwrap(await client.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } })),
    refetchInterval: pollEvery(options),
  })
}

export function useUseCases() {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.useCases(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/use-cases')).use_cases,
  })
}

export function useUseCase(useCaseId: string, enabled = true) {
  const client = useApiClient()
  const user = useDevUser()
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

export function useSuggest() {
  const client = useApiClient()
  return useMutation({
    mutationFn: async (text: string) => unwrap(await client.POST('/api/v1/use-cases/suggest', { body: { text } })),
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runs'] }),
  })
}

export function useApproval(approvalId: string, options?: QueryOptions) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.approval(user, approvalId),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/approvals/{approval_id}', { params: { path: { approval_id: approvalId } } })),
    refetchInterval: pollEvery(options),
  })
}

function refreshAfterChange(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(
    ['approval', 'run', 'runs', 'teams-messages', 'jira-tickets'].map((key) =>
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

export function useTroubleshoot(runId: string, enabled: boolean) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.troubleshoot(user, runId),
    queryFn: async () =>
      unwrap(await client.GET('/api/v1/runs/{run_id}/troubleshoot', { params: { path: { run_id: runId } } })),
    enabled,
  })
}

export function useTeamsMessages(options?: QueryOptions) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.teamsMessages(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/teams-stub/messages')).messages,
    refetchInterval: pollEvery(options),
  })
}

export function useMockJiraTickets(options?: QueryOptions) {
  const client = useApiClient()
  const user = useDevUser()
  return useQuery({
    queryKey: keys.jiraTickets(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/mock-jira/tickets')).tickets,
    refetchInterval: pollEvery(options),
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
