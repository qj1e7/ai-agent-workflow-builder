import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { ApiProvider } from '../../api/context'
import { useRetry, type RetryAfter } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { Actor } from '../../api/types'
import { InSidePanel } from '../../ui/sidePanel'
import { Toast } from '../../ui/Toast'
import { RunPlaceContext, type RunPlace } from '../run/place'
import { useRetryAfter } from './HomeItem'
import { retriedFirstWords } from './home'

const CAROL: Actor = { kind: 'user', id: 'carol', display: 'Carol' }
const ALICE: Actor = { kind: 'user', id: 'alice', display: 'Alice' }
const PLATFORM: Actor = { kind: 'platform', id: 'platform', display: 'Platform' }

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const event = (seq: number, kind: string, actor: Actor) => ({ run_id: 'run_1', seq, ts: '2026-11-15T01:00:00Z', actor, summary: '', kind, data: {} })
const STOPPED_THEN_CAROL = [event(1, 'run_created', ALICE), event(2, 'run_failed', PLATFORM), event(3, 'run_retried', ALICE), event(4, 'run_failed', PLATFORM), event(5, 'run_retried', CAROL)]

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

/** Presses Retry once against a platform that answers the retry with `status`, and returns what happened, in order. */
async function press(status: number, events: () => Response = () => json({ events: STOPPED_THEN_CAROL })): Promise<string[]> {
  const happened: string[] = []
  const queryClient = new QueryClient()
  vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(() => {
    happened.push('the page reads the run again')
    return Promise.resolve()
  })
  const after: RetryAfter = {
    retried: () => happened.push('retried'),
    retriedFirst: (by) => happened.push(`retried first by ${by?.display ?? 'nobody named'}`),
  }
  let retry: ReturnType<typeof useRetry> | undefined
  function Probe() {
    retry = useRetry('run_1', after)
    return null
  }
  within(<Probe />, (request) => {
    if (request.method === 'POST') return status === 202 ? json({ state: 'pending' }, 202) : json({ detail: 'The run is working, not failed' }, status)
    return events()
  }, queryClient)
  await retry?.mutateAsync().catch(() => undefined)
  return [...new Set(happened)]
}

describe('a Retry press another Operator beat', () => {
  it('learns who retried the run from its newest retry, before the page reads the run again and takes Retry away', async () => {
    expect(await press(409)).toEqual(['retried first by Carol', 'the page reads the run again'])
  })

  it('names nobody when the run can’t be read, and still lets the page read it again', async () => {
    expect(await press(409, () => json({ detail: 'down' }, 503))).toEqual(['retried first by nobody named', 'the page reads the run again'])
  })

  it('is not a lost race when the platform takes the retry, or refuses it for another reason', async () => {
    expect(await press(202)).toEqual(['retried', 'the page reads the run again'])
    expect(await press(500), 'the button says that problem itself').toEqual(['the page reads the run again'])
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
    after.retriedFirst(CAROL)
    expect(place.say).toHaveBeenCalledWith('Carol already retried this run.')
    expect(place.focus).toHaveBeenCalledOnce()
    after.retried()
    expect(place.focus, 'a retry it took keeps her on the run, with focus on its heading').toHaveBeenCalledTimes(2)
  })

  it('in the side panel: the panel goes back to its top and its heading takes focus', () => {
    const backToTop = vi.fn()
    const after = afterIn((node) => <InSidePanel.Provider value={backToTop}>{node}</InSidePanel.Provider>)
    after.retriedFirst(CAROL)
    expect(backToTop).toHaveBeenCalledOnce()
  })

  it('reads the words aloud: the place’s message is a status a screen reader announces', () => {
    const html = renderToStaticMarkup(<Toast message={{ id: 1, text: retriedFirstWords(CAROL, 'alice') }} onDismiss={() => undefined} />)
    expect(html).toMatch(/<p role="status"[^>]*>Carol already retried this run\.<\/p>/)
  })
})
