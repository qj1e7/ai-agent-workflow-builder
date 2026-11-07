import { useMutation, useQueryClient } from '@tanstack/react-query'
import { unwrap } from './client'
import { useApiClient } from './context'

export interface SupportReport {
  readonly runId: string
  readonly note: string
  readonly idempotencyKey: string
}

/**
 * Keeps a report to support about a run as a team request. The same key sent again answers the same request, so a
 * second press or a retry after a lost answer never makes a second one.
 */
export function useReportToSupport() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ runId, note, idempotencyKey }: SupportReport) =>
      unwrap(
        await client.POST('/api/v1/team-requests', {
          params: { header: { 'Idempotency-Key': idempotencyKey } },
          body: { kind: 'support', about: { run_id: runId }, note },
        }),
      ),
    onSettled: () => Promise.all(['home', 'team-requests', 'run'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}

export interface TeamAsk {
  readonly capability: string
  readonly note: string
  readonly idempotencyKey: string
}

/** Keeps an Ask the team request: something the platform can't do yet, as the person put it. The same key answers the same request. */
export function useAskTheTeam() {
  const client = useApiClient()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ capability, note, idempotencyKey }: TeamAsk) =>
      unwrap(
        await client.POST('/api/v1/team-requests', {
          params: { header: { 'Idempotency-Key': idempotencyKey } },
          body: { kind: 'ask_the_team', about: { capability }, note },
        }),
      ),
    onSettled: () => Promise.all(['home', 'team-requests'].map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  })
}
