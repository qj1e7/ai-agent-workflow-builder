import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../contracts/fixtures/builder/use-case.json'
import type { UseCaseView } from './types'
import { QueryClient } from '@tanstack/react-query'
import { keys } from './queries'
import { applySavedView, withView } from './workflowQueries'

const NEWER = agentUseCase as UseCaseView
const OLDER = watchlistUseCase as UseCaseView

describe('the cached list after a change', () => {
  it('replaces the workflow the platform answered with', () => {
    const paused = { ...NEWER, state: 'paused' as const }
    expect(withView([NEWER, OLDER], paused)).toEqual([paused, OLDER])
  })

  it('puts a restored workflow where the platform would list it, the newest first', () => {
    expect(withView([OLDER], NEWER).map((item) => item.use_case_id)).toEqual(['uc_01JD0', 'uc_01JB7'])
    expect(withView([NEWER], OLDER).map((item) => item.use_case_id)).toEqual(['uc_01JD0', 'uc_01JB7'])
  })
})

describe('the cache after a schedule is saved', () => {
  it('holds the saved workflow, in the list too, so the page shows it at once', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(keys.useCase('me', NEWER.use_case_id), NEWER)
    queryClient.setQueryData(keys.useCases('me'), [NEWER, OLDER])
    const saved = { ...NEWER, next_run_at: '2026-11-09T01:00:00Z' }

    applySavedView(queryClient, 'me', saved)

    expect(queryClient.getQueryData(keys.useCase('me', NEWER.use_case_id))).toEqual(saved)
    expect(queryClient.getQueryData(keys.useCases('me'))).toEqual([saved, OLDER])
  })
})
