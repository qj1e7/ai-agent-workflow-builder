import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRef } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { WatchlistView } from '../../api/types'
import { clicksByLabel as drawn, pressByLabel as press } from '../../ui/testing'
import { Schedule, TurnOffSchedule } from './Schedule'

vi.mock('../../ui/Button', async (importOriginal) => (await import('../../ui/testing')).recordingButtons(await importOriginal()))

const LIST = statuses as WatchlistView
const settled = () => new Promise((resolve) => setTimeout(resolve, 0))
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

function draw() {
  drawn.clear()
  const sent: string[] = []
  const platform = (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    sent.push(`${request.method} ${new URL(request.url).pathname}`)
    return Promise.resolve(new Response(null, { status: 204 }))
  }
  const session = createDevSession(null)
  const html = renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={session} platformFetch={platform} origin="http://portal.test" baseUrl="http://portal.test">
        <MemoryRouter>
          <Schedule schedule={LIST.schedule} version={LIST.version} operator paused={false} useCaseId={LIST.use_case_id} answeredAt={0} onResumed={() => undefined} held={null} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
  return { html, sent }
}

const QUESTION = 'Turn off the schedule? The watchlist won’t be checked until someone sets one again.'
const buttonsIn = (html: string) => [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].map((m) => ({ label: text(m[2] ?? ''), attributes: m[1] ?? '' }))

function ask(over: Partial<Parameters<typeof TurnOffSchedule>[0]> = {}) {
  drawn.clear()
  const props = { confirming: true, busy: false, offButton: createRef<HTMLButtonElement>(), onAsk: vi.fn(), onKeep: vi.fn(), onYes: vi.fn(), ...over }
  return { props, html: renderToStaticMarkup(<TurnOffSchedule {...props} />) }
}

describe('turning off the watchlist schedule', () => {
  it('sends nothing on the first press of Turn off schedule', async () => {
    const { html, sent } = draw()
    expect(text(html)).toContain('Turn off schedule')
    expect(text(html)).not.toContain('Turn off the schedule?')
    press('Turn off schedule')
    await settled()
    expect(sent).toEqual([])
  })

  it('opens the question from Turn off schedule', () => {
    const { props } = ask({ confirming: false })
    press('Turn off schedule')
    expect(props.onAsk).toHaveBeenCalledOnce()
    expect(props.onYes).not.toHaveBeenCalled()
  })

  it('asks in the approved words, Keep it first and the destructive Yes last', () => {
    const { html } = ask()
    expect(text(html)).toContain(QUESTION)
    const buttons = buttonsIn(html)
    expect(buttons.map((b) => b.label)).toEqual(['Keep it', 'Yes, turn it off'])
    expect(buttons[1]?.attributes).toMatch(/class="[^"]*dangerOutline/)
  })

  it('changes nothing on Keep it', () => {
    const { props } = ask()
    press('Keep it')
    expect(props.onKeep).toHaveBeenCalledOnce()
    expect(props.onYes).not.toHaveBeenCalled()
  })

  it('turns it off once on Yes, and holds a second press while it turns off', () => {
    const { props } = ask()
    press('Yes, turn it off')
    expect(props.onYes).toHaveBeenCalledOnce()
    const busy = ask({ busy: true })
    press('Yes, turn it off')
    expect(busy.props.onYes).not.toHaveBeenCalled()
  })
})
