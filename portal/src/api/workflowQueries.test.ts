import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../contracts/fixtures/cards/use-case.json'
import watchlistUseCase from '../../../contracts/fixtures/builder/use-case.json'
import setUpCreated from '../../../contracts/fixtures/builder/agent-use-case.off.created.json'
import draftUseCase from '../../../contracts/fixtures/builder/use-case.draft.json'
import type { UseCaseCreated, UseCaseView } from './types'
import { QueryClient } from '@tanstack/react-query'
import { keys } from './queries'
import type { ApiClient } from './client'
import { applySavedView, holdSetUp, saveScheduleOptions, setUpOffOptions, testStarted, turnOnOptions, withView, type SetUp } from './workflowQueries'

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

describe('saving a workflow’s schedule', () => {
  it('sends it to the workflow’s schedule route and keeps the answer in the cache', async () => {
    const queryClient = new QueryClient()
    const saved = { ...NEWER, next_run_at: '2026-11-09T01:00:00Z' }
    const sent: unknown[] = []
    const client = { PUT: (path: string, init: unknown) => (sent.push([path, init]), Promise.resolve({ data: saved, response: { ok: true, status: 200 } })) } as unknown as ApiClient
    const options = saveScheduleOptions(client, queryClient, 'me', NEWER.use_case_id)

    const view = await options.mutationFn({ day: 'monday', at: '09:00' })
    options.onSuccess(view)

    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/schedule', { params: { path: { use_case_id: NEWER.use_case_id } }, body: { day: 'monday', at: '09:00', via: 'page' } }]])
    expect(queryClient.getQueryData(keys.useCase('me', NEWER.use_case_id))).toEqual(saved)
  })
})

describe('setting a workflow up as a draft, testing it and turning it on', () => {
  const created = setUpCreated as UseCaseCreated
  const draftView = draftUseCase as UseCaseView
  const client = (answer: unknown, sent: unknown[]) =>
    ({ POST: (path: string, init: unknown) => (sent.push([path, init]), Promise.resolve({ data: answer, response: { ok: true, status: 200 } })) }) as unknown as ApiClient

  it('always asks for a draft, and holds the build log and blocks the platform answered with for the card and the build panel', async () => {
    const queryClient = new QueryClient()
    const sent: unknown[] = []
    const options = setUpOffOptions(client(created, sent), queryClient, 'me', () => 1_000)
    const body = { name: 'LangGraph release check', instruction: 'Check it.', agents: [], schedule: { day: 'monday' as const, at: '08:00' }, on: true }

    options.onSuccess(await options.mutationFn(body))

    expect(sent).toEqual([['/api/v1/agent-use-cases', { body: { ...body, on: false } }]])
    expect(queryClient.getQueryData(keys.setUp('me', created.use_case_id))).toEqual({ created, at: 1_000, testRunId: null })
  })

  it('keeps the test run the card started with the set-up, and keeps it when the test is started again', () => {
    const queryClient = new QueryClient()
    holdSetUp(queryClient, 'me', created, 1_000)
    testStarted(queryClient, 'me', created.use_case_id, 'run_01')
    expect(queryClient.getQueryData<SetUp>(keys.setUp('me', created.use_case_id))?.testRunId).toBe('run_01')
    testStarted(queryClient, 'me', 'uc_unknown', 'run_02')
    expect(queryClient.getQueryData(keys.setUp('me', 'uc_unknown')), 'a test run of a set-up it never held is not made up').toBeUndefined()
  })

  it('turns it on through the turn-on route, and holds what the platform says it is now', async () => {
    const queryClient = new QueryClient()
    const on = { ...draftView, state: 'on' as const, next_run_at: '2026-11-16T00:00:00Z' }
    const sent: unknown[] = []
    const options = turnOnOptions(client(on, sent), queryClient, 'me')

    options.onSuccess(await options.mutationFn(draftView.use_case_id))

    expect(sent).toEqual([['/api/v1/use-cases/{use_case_id}/turn-on', { params: { path: { use_case_id: draftView.use_case_id } } }]])
    expect(queryClient.getQueryData(keys.useCase('me', draftView.use_case_id))).toEqual(on)
  })
})
