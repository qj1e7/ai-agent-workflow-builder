import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
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
  it('leaves the reason to the card: the run page does not hand the stage a note of its own', () => {
    const page = readFileSync(new URL('./RunPage.tsx', import.meta.url), 'utf8')
    expect(page).not.toMatch(/stopNote/)
  })
})
