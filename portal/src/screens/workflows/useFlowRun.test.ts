import failed from '@contracts/fixtures/views/failure.final.json'
import success from '@contracts/fixtures/runs/failure.json'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { createApiClient } from '../../api/client'
import { keys } from '../../api/queries'
import { authorizedFetch, createDevSession } from '../../api/session'
import type { RunView } from '../../api/types'
import { flowRunOptions } from './useFlowRun'
import { runAt } from './workflow'

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

describe('the latest run read for the flow diagram', () => {
  it('reads the run once, from the events endpoint, and names it by the time the app gives a run', async () => {
    const { urls, client, queryClient } = setup()
    const read = await queryClient.fetchQuery(flowRunOptions(client, 'alice', RUN))
    expect(urls).toEqual([`http://portal.test/api/v1/runs/${RUN.run_id}/events?after=0`])
    expect(read.runId).toBe(RUN.run_id)
    expect(read.events).toHaveLength(success.length)
    expect(read.startedAt).toBe(runAt(RUN))
    expect(read.startedAt).not.toBe(RUN.started_at)
  })

  it('is cached under its own key, which holds the run and its last event', () => {
    const { client } = setup()
    expect(flowRunOptions(client, 'alice', RUN).queryKey).toEqual(keys.runFlow('alice', RUN.run_id, 'last_seq' in RUN ? RUN.last_seq : 0))
  })

  it('keeps the states on the page while the run moves on and is read again, but never another run\'s', async () => {
    const { client, queryClient, hold, release } = setup()
    await queryClient.fetchQuery(flowRunOptions(client, 'alice', RUN))
    hold(true)
    const moved = { ...RUN, last_seq: ('last_seq' in RUN ? RUN.last_seq : 0) + 1 } as RunView
    const watch = new QueryObserver(queryClient, flowRunOptions(client, 'alice', moved))
    const stop = watch.subscribe(() => undefined)
    expect(watch.getCurrentResult().isPlaceholderData).toBe(true)
    expect(watch.getCurrentResult().data?.runId).toBe(RUN.run_id)
    watch.setOptions(flowRunOptions(client, 'alice', { ...RUN, run_id: 'run_other', last_seq: 1 } as RunView))
    expect(watch.getCurrentResult().data).toBeUndefined()
    release()
    stop()
  })
})
