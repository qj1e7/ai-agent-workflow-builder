import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { IconCheck, IconLock, IconX } from './icons'
import { SmallStepLine, type SmallStep } from './SmallStepLine'

const STEPS: readonly SmallStep[] = [
  { key: 'when', icon: IconCheck, state: 'done' },
  { key: 'read', icon: IconX, state: 'stop' },
  { key: 'gate', icon: IconLock, state: 'unreached' },
]

describe('the small step line', () => {
  const html = renderToStaticMarkup(<SmallStepLine steps={STEPS} label="Last run: Today 8:00: GitHub didn’t answer" />)

  it('is one picture, read out as its label, not as one shape per step', () => {
    expect(html).toMatch(/^<span[^>]*role="img"[^>]*aria-label="Last run: Today 8:00: GitHub didn’t answer"/)
    expect([...html.matchAll(/<svg[^>]*>/g)].every((match) => match[0].includes('aria-hidden="true"'))).toBe(true)
  })

  it('draws each step in order, in the state its last run left it', () => {
    expect([...html.matchAll(/data-state="([a-z]+)"/g)].map((match) => match[1])).toEqual(['done', 'stop', 'unreached'])
  })

  it('comes in the sketch’s two sizes', () => {
    const small = renderToStaticMarkup(<SmallStepLine steps={STEPS} label="No runs yet" size="small" />)
    expect(small).toMatch(/^<span class="[^"]*_small_/)
    expect(html).not.toMatch(/^<span class="[^"]*_small_/)
  })
})
