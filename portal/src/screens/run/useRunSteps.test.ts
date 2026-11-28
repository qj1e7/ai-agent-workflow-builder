import failed from '@contracts/fixtures/views/failure.final.json'
import success from '@contracts/fixtures/runs/failure.json'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { createApiClient } from '../../api/client'
import { keys } from '../../api/queries'
import { authorizedFetch, createDevSession } from '../../api/session'
import type { RunView } from '../../api/types'
import { runStepsOptions } from './useRunSteps'

const RUN = failed as unknown as RunView
const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))

function setup() {
  const urls: string[] = []
  let release: () => void = () => undefined
  let hold = false
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    urls.push(new Request(input, init).url)
    if (hold) await new Promise<void>((resolve) => (release = resolve))
    return json({ events: success })
  }) as typeof fetch
  const session = createDevSession(null)
  session.choose('alice')
  const client = createApiClient(authorizedFetch(session, fetchImpl, 'http://portal.test'), 'http://portal.test')
  const queryClient = new QueryClient()
  return { urls, client, queryClient, hold: (on: boolean) => (hold = on), release: () => release() }
}

describe('a run read as steps, for the board, the slim list and the workflow page', () => {
  it('reads the run once, from the events endpoint, in one request', async () => {
    const { urls, client, queryClient } = setup()
    const events = await queryClient.fetchQuery(runStepsOptions(client, 'alice', { runId: RUN.run_id, version: RUN.last_seq }))
    expect(urls).toEqual([`http://portal.test/api/v1/runs/${RUN.run_id}/events?after=0`])
    expect(events).toHaveLength(success.length)
  })

  it('has one key, which holds the run and the version it was read at, a state or a last event', () => {
    const { client } = setup()
    expect(runStepsOptions(client, 'alice', { runId: 'run_1', version: 7 }).queryKey).toEqual(keys.runSteps('alice', 'run_1', 7))
    expect(keys.runSteps('alice', 'run_1', 'awaiting_approval')).not.toEqual(keys.runSteps('alice', 'run_1', 'succeeded'))
    expect(keys.runSteps('alice', 'run_1', 7)).not.toEqual(keys.runSteps('alice', 'run_2', 7))
  })

  it('does not read a failed read again, so a line is never drawn from a guess', () => {
    const { client } = setup()
    expect(runStepsOptions(client, 'alice', { runId: 'run_1', version: 1 }).retry).toBe(false)
  })

  it('keeps the states on the page while the same run moves on and is read again, but never another run\'s', async () => {
    const { client, queryClient, hold, release } = setup()
    const read = { runId: RUN.run_id, version: RUN.last_seq }
    await queryClient.fetchQuery(runStepsOptions(client, 'alice', read))
    hold(true)
    const watch = new QueryObserver(queryClient, runStepsOptions(client, 'alice', read))
    const stop = watch.subscribe(() => undefined)
    watch.setOptions(runStepsOptions(client, 'alice', { ...read, version: read.version + 1 }))
    expect(watch.getCurrentResult().isPlaceholderData).toBe(true)
    expect(watch.getCurrentResult().data).toHaveLength(success.length)
    watch.setOptions(runStepsOptions(client, 'alice', { runId: 'run_other', version: 1 }))
    expect(watch.getCurrentResult().data).toBeUndefined()
    release()
    stop()
  })
})
