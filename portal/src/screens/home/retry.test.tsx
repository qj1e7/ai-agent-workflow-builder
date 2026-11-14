import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import { ApiProvider } from '../../api/context'
import { RetriedFirst, useRetry, type RetryAfter } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { Actor, HomeOut } from '../../api/types'
import { InSidePanel } from '../../ui/sidePanel'
import { RunPlaceContext, type RunPlace } from '../run/place'
import { useRetryAfter } from './HomeItem'
import { needsOf, retryProblem } from './home'
import { NeedRows } from './NeedsSection'

const CAROL: Actor = { kind: 'user', id: 'carol', display: 'Carol' }
const ALICE: Actor = { kind: 'user', id: 'alice', display: 'Alice' }
const PLATFORM: Actor = { kind: 'platform', id: 'platform', display: 'Platform' }

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const event = (seq: number, kind: string, actor: Actor) => ({ run_id: 'run_1', seq, ts: '2026-11-15T01:00:00Z', actor, summary: '', kind, data: {} })
const N8N: Actor = { kind: 'workflow', id: 'n8n', display: 'n8n' }
/** Alice retried an earlier stop, the run stopped again, and then Carol retried it. */
const CAROL_AFTER_THE_STOP = [event(1, 'run_created', ALICE), event(2, 'run_failed', PLATFORM), event(3, 'run_retried', ALICE), event(4, 'run_failed', PLATFORM), event(5, 'run_retried', CAROL), event(6, 'leg_dispatched', PLATFORM)]
/** Alice retried an earlier stop, the run stopped again, and then a retry started in n8n joined it, which writes no run_retried. */
const N8N_AFTER_THE_STOP = [event(1, 'run_created', ALICE), event(2, 'run_failed', PLATFORM), event(3, 'run_retried', ALICE), event(4, 'run_failed', PLATFORM), event(5, 'execution_linked', N8N)]
const STILL_STOPPED = 'This stop can’t be retried. Ask a maintainer to fix it, then start a new run.'

function within(node: ReactNode, platform: (request: Request) => Response, queryClient = new QueryClient()): string {
  const session = createDevSession(null)
  session.choose('alice')
  const answer = (input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(platform(new Request(input, init)))
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={answer} origin="http://portal.test" baseUrl="http://portal.test">
        <MemoryRouter>{node}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

interface Platform {
  /** How the platform answers the retry. */
  readonly retry: number
  /** The run's state when the Portal reads it after a refusal. */
  readonly state?: string
  readonly events?: () => Response
}

/** Presses Retry once, and returns what happened in order, and the error the press ended with. */
async function press({ retry: status, state = 'working', events = () => json({ events: CAROL_AFTER_THE_STOP }) }: Platform): Promise<{ happened: string[]; error: unknown }> {
  const happened: string[] = []
  const queryClient = new QueryClient()
  vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(() => {
    happened.push('the page reads the run again')
    return Promise.resolve()
  })
  const after: RetryAfter = {
    retried: () => happened.push('retried'),
    retriedFirst: (by) => happened.push(`retried first by ${by ?? 'nobody named'}`),
  }
  let retry: ReturnType<typeof useRetry> | undefined
  function Probe() {
    retry = useRetry('run_1', after)
    return null
  }
  within(
    <Probe />,
    (request) => {
      const path = new URL(request.url).pathname
      if (request.method === 'POST') return status === 202 ? json({ state: 'pending' }, 202) : json({ detail: status === 409 && state === 'failed' ? STILL_STOPPED : `The run is ${state}, not failed` }, status)
      if (path.endsWith('/events')) return events()
      return json({ run_id: 'run_1', state })
    },
    queryClient,
  )
  const error = await retry?.mutateAsync().then(
    () => null,
    (caught: unknown) => caught,
  )
  return { happened: [...new Set(happened)], error }
}

describe('a Retry press another Operator beat', () => {
  it('names the person whose retry came after the run’s newest stop, before the page reads the run again and takes Retry away', async () => {
    const { happened, error } = await press({ retry: 409 })
    expect(happened).toEqual(['retried first by carol', 'the page reads the run again'])
    expect(error, 'the button leaves the telling to the place').toBeInstanceOf(RetriedFirst)
  })

  it('names nobody when a retry started in n8n took the run on, though Alice retried an earlier stop', async () => {
    expect((await press({ retry: 409, events: () => json({ events: N8N_AFTER_THE_STOP }) })).happened).toEqual(['retried first by nobody named', 'the page reads the run again'])
  })

  it('names nobody when the run’s events can’t be read', async () => {
    expect((await press({ retry: 409, events: () => json({ detail: 'down' }, 503) })).happened).toEqual(['retried first by nobody named', 'the page reads the run again'])
  })

  it('is no race when the run is still stopped: the button says the platform’s own words', async () => {
    const { happened, error } = await press({ retry: 409, state: 'failed' })
    expect(happened).toEqual(['the page reads the run again'])
    expect(error).not.toBeInstanceOf(RetriedFirst)
    expect(retryProblem(error, (refused) => (refused instanceof Error ? refused.message : ''))).toBe(`Could not retry the run. ${STILL_STOPPED}`)
  })

  it('is no race when the platform takes the retry, or refuses it for another reason', async () => {
    expect((await press({ retry: 202 })).happened).toEqual(['retried', 'the page reads the run again'])
    expect((await press({ retry: 500 })).happened, 'the button says that problem itself').toEqual(['the page reads the run again'])
  })
})

describe('where Retry is drawn', () => {
  it('is never in the Needs rows that Workflows and the chat’s Needs answer draw, which only open the run, so the race is told on the run', () => {
    const html = within(<NeedRows needs={needsOf(aliceHome as HomeOut).shown} now={new Date('2026-11-04T15:00:00+08:00')} more={null} />, () => json({}, 404))
    expect(html).toContain('data-kind="stopped"')
    expect(html).not.toContain('<button')
  })
})

/** What a press does where the button is drawn. */
function afterIn(wrap: (node: ReactNode) => ReactNode): RetryAfter {
  let after: RetryAfter | undefined
  function Probe() {
    after = useRetryAfter('run_1')
    return null
  }
  within(wrap(<Probe />), () => json({}, 404))
  if (!after) throw new Error('drawn')
  return after
}

describe('where a lost race is said, and where focus goes', () => {
  it('on the run page or the run card: says who retried it in that place’s message, and its heading takes focus', () => {
    const place: RunPlace = { focus: vi.fn(), say: vi.fn() }
    const after = afterIn((node) => <RunPlaceContext.Provider value={place}>{node}</RunPlaceContext.Provider>)
    after.retriedFirst('carol')
    expect(place.say).toHaveBeenCalledWith('Carol already retried this run.')
    expect(place.focus).toHaveBeenCalledOnce()
    after.retried()
    expect(place.focus, 'a retry it took keeps her on the run, with focus on its heading').toHaveBeenCalledTimes(2)
  })

  it('in the side panel: the panel goes back to its top and its heading takes focus', () => {
    const backToTop = vi.fn()
    const after = afterIn((node) => <InSidePanel.Provider value={backToTop}>{node}</InSidePanel.Provider>)
    after.retriedFirst('carol')
    expect(backToTop).toHaveBeenCalledOnce()
  })

})
