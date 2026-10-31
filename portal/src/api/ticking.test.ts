import { afterEach, describe, expect, it, vi } from 'vitest'

const hooks = vi.hoisted(() => ({ deps: [] as unknown[][], redraw: () => undefined }))

vi.mock('react', () => ({
  useReducer: () => [0, hooks.redraw],
  useState: (start: unknown) => [typeof start === 'function' ? (start as () => unknown)() : start, hooks.redraw],
  useEffect: (_run: unknown, deps: unknown[]) => void hooks.deps.push(deps),
}))

const { CLOCK_TICK_MS, keepTime, useNow } = await import('./ticking')

afterEach(() => {
  vi.useRealTimers()
  hooks.deps.length = 0
})

describe('a clock that keeps up on a page left open', () => {
  it('redraws the page every tick, and stops when told to', () => {
    vi.useFakeTimers()
    let ticks = 0
    const stop = keepTime(() => ticks++)
    vi.advanceTimersByTime(CLOCK_TICK_MS * 2)
    expect(ticks).toBe(2)
    stop()
    vi.advanceTimersByTime(CLOCK_TICK_MS * 3)
    expect(ticks).toBe(2)
  })

  it('reads the time fresh on every draw', () => {
    let wall = new Date('2026-11-04T23:59:30+08:00')
    expect(useNow(() => wall)).toEqual(wall)
    wall = new Date('2026-11-05T00:00:30+08:00')
    expect(useNow(() => wall)).toEqual(wall)
  })

  it('keeps one timer when the page draws again with a new clock function', () => {
    useNow(() => new Date())
    useNow(() => new Date())
    expect(hooks.deps).toEqual([[], []])
  })
})
