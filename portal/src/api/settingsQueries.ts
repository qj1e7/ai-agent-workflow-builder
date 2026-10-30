import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient, useCacheScope } from './context'
import type { AddPersonIn, ConfirmationDecisionIn } from './types'

const settingsKeys = {
  people: (user: string) => ['people', user] as const,
  confirmations: (user: string) => ['confirmations', user] as const,
  history: (user: string) => ['settings-history', user] as const,
}

export function usePeopleList() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: settingsKeys.people(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/people')).people,
  })
}

export function useConfirmations() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: settingsKeys.confirmations(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/confirmations')).confirmations,
  })
}

export function useSettingsHistory() {
  const client = useApiClient()
  const user = useCacheScope()
  return useQuery({
    queryKey: settingsKeys.history(user),
    queryFn: async () => unwrap(await client.GET('/api/v1/settings/history')).changes,
  })
}

function refreshPeople(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(
    ['people', 'confirmations', 'settings-history', 'me', 'dev-users'].map((key) =>
      queryClient.invalidateQueries({ queryKey: [key] }),
    ),
  )
}

export function useAddPerson() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: AddPersonIn) => unwrap(await client.POST('/api/v1/people', { body })),
    onSettled: () => refreshPeople(queryClient),
  })
}

interface OperatorChange {
  personId: string
  operator: boolean
}

export function useSetOperator() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ personId, operator }: OperatorChange) =>
      unwrap(
        await client.PUT('/api/v1/people/{person_id}/operator', {
          params: { path: { person_id: personId } },
          body: { operator },
        }),
      ),
    onSettled: () => refreshPeople(queryClient),
  })
}

export function useAskApprover() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (personId: string) =>
      unwrap(await client.POST('/api/v1/people/{person_id}/approver', { params: { path: { person_id: personId } } })),
    onSettled: () => refreshPeople(queryClient),
  })
}

export function useRemoveApprover() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (personId: string) =>
      unwrap(await client.DELETE('/api/v1/people/{person_id}/approver', { params: { path: { person_id: personId } } })),
    onSettled: () => refreshPeople(queryClient),
  })
}

interface ConfirmationDecision extends ConfirmationDecisionIn {
  confirmationId: string
}

export function useDecideConfirmation() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ confirmationId, verdict, digest }: ConfirmationDecision) =>
      unwrap(
        await client.POST('/api/v1/confirmations/{confirmation_id}/decisions', {
          params: { path: { confirmation_id: confirmationId } },
          body: { verdict, digest },
        }),
      ),
    onSettled: () => refreshPeople(queryClient),
  })
}
