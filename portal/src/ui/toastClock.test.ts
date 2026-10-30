import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readMs, RESUME_MS, startToastClock } from './toastClock'

describe('how long a message stays', () => {
  it('grows with its length, from 2 seconds to at most 10', () => {
    expect(readMs('')).toBe(2_000)
    expect(readMs('Paused.')).toBe(2_000 + 7 * 45)
    expect(readMs('x'.repeat(500))).toBe(10_000)
  })
})

describe('the clock of a message without Undo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('hides the message after its reading time', () => {
    const hide = vi.fn()
    startToastClock(3_000, hide)
    vi.advanceTimersByTime(2_999)
    expect(hide).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(hide).toHaveBeenCalledOnce()
  })

  it('waits while the pointer or focus is on it, or the tab is hidden, then gives 4 more seconds', () => {
    for (const reason of ['hover', 'focus', 'hidden'] as const) {
      const hide = vi.fn()
      const clock = startToastClock(3_000, hide)
      vi.advanceTimersByTime(2_000)
      clock.hold(reason)
      vi.advanceTimersByTime(60_000)
      expect(hide, reason).not.toHaveBeenCalled()
      clock.release(reason)
      vi.advanceTimersByTime(RESUME_MS - 1)
      expect(hide, reason).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1)
      expect(hide, reason).toHaveBeenCalledOnce()
    }
  })

  it('keeps waiting until every hold is let go', () => {
    const hide = vi.fn()
    const clock = startToastClock(3_000, hide)
    clock.hold('hover')
    clock.hold('focus')
    clock.release('hover')
    vi.advanceTimersByTime(60_000)
    expect(hide).not.toHaveBeenCalled()
    clock.release('focus')
    vi.advanceTimersByTime(RESUME_MS)
    expect(hide).toHaveBeenCalledOnce()
  })

  it('never fires after it is stopped', () => {
    const hide = vi.fn()
    const clock = startToastClock(3_000, hide)
    clock.stop()
    clock.release('hover')
    vi.advanceTimersByTime(60_000)
    expect(hide).not.toHaveBeenCalled()
  })
})
