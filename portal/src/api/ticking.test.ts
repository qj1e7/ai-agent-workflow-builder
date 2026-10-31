import { afterEach, describe, expect, it, vi } from 'vitest'
import { CLOCK_TICK_MS, keepTime } from './ticking'

afterEach(() => vi.useRealTimers())

describe('a clock that keeps up on a page left open', () => {
  it('reads the time again every tick and tells the page', () => {
    vi.useFakeTimers()
    let wall = new Date('2026-11-04T23:59:30+08:00')
    const seen: string[] = []
    const stop = keepTime(() => wall, (at) => seen.push(at.toISOString()))
    expect(seen).toEqual([])
    wall = new Date('2026-11-05T00:00:30+08:00')
    vi.advanceTimersByTime(CLOCK_TICK_MS)
    expect(seen).toEqual([wall.toISOString()])
    stop()
    vi.advanceTimersByTime(CLOCK_TICK_MS * 3)
    expect(seen).toHaveLength(1)
  })
})
