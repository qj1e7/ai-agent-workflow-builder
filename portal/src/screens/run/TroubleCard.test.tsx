import { MemoryRouter } from 'react-router'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunStage } from './RunStage'
import type { Station } from './runModel'
import { TroubleCard } from './TroubleCard'

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

describe("the AI troubleshooter's card under a stop", () => {
  it('names the troubleshooter above its answers and keeps the answers and buttons it is given', () => {
    const html = renderToStaticMarkup(
      <TroubleCard face="idle" at={0.375}>
        <p>the answers</p>
        <button type="button">Retry</button>
      </TroubleCard>,
    )
    expect(text(html)).toMatch(/^AI troubleshooter the answers Retry$/)
    expect(html).toContain('data-face="orb"')
  })

  it('points at the stopped step with its notch, and has no notch when the stage is not drawn', () => {
    const pointing = renderToStaticMarkup(
      <TroubleCard face="idle" at={0.375}>
        x
      </TroubleCard>,
    )
    expect(pointing).toContain('--at:0.375')
    expect(pointing).toContain('data-notch')
    const plain = renderToStaticMarkup(
      <TroubleCard face="idle" at={null}>
        x
      </TroubleCard>,
    )
    expect(plain).not.toContain('data-notch')
  })
})

describe('the stop is said once', () => {
  it('leaves the reason to the card: a stopped step has no note of its own unless one is handed to the stage', () => {
    const stations: Station[] = [
      { key: 'trigger', spot: { at: 'started' }, label: 'Started', icon: 'schedule', agent: null, state: 'done', face: 'idle', under: null },
      { key: 'agent:0', spot: { at: 'gate' }, label: 'Ask', icon: 'gate', agent: null, state: 'err', face: 'idle', under: null },
    ]
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <RunStage stations={stations} arrivedLive={null} phase="failed" />
      </MemoryRouter>,
    )
    expect(html).not.toMatch(/class="[^"]*why/)
  })
})
