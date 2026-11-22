import { describe, expect, it } from 'vitest'
import { landingOf, scrollsToDecision } from './landing'

describe('where a run page opens', () => {
  it('lands on a decision that waits for a yes, from the run or from its approval', () => {
    expect(landingOf('awaiting_approval', false)).toBe('decide')
    expect(landingOf('awaiting_approval', true)).toBe('decide')
  })

  it('opens a stop, a decline or a decided approval at its top, and a run with nothing to decide nowhere in particular', () => {
    expect(landingOf('failed', false)).toBe('read')
    expect(landingOf('rejected', false)).toBe('read')
    expect(landingOf('succeeded', true)).toBe('read')
    expect(landingOf('succeeded', false)).toBeNull()
    expect(landingOf('working', false)).toBeNull()
  })

  it('always brings a waiting decision in, even when its top already shows at the bottom of the window', () => {
    expect(scrollsToDecision('decide', { top: 411, bottom: 1099 }, 420)).toBe(true)
    expect(scrollsToDecision('decide', { top: 120, bottom: 300 }, 900)).toBe(true)
  })

  it('leaves a stop to read where it is while any of it shows, and scrolls only when it is off screen', () => {
    expect(scrollsToDecision('read', { top: 392, bottom: 597 }, 900)).toBe(false)
    expect(scrollsToDecision('read', { top: 880, bottom: 1080 }, 900)).toBe(false)
    expect(scrollsToDecision('read', { top: 900, bottom: 1100 }, 900)).toBe(true)
    expect(scrollsToDecision('read', { top: -300, bottom: 0 }, 900)).toBe(true)
  })
})
