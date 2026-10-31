import { useEffect, useReducer } from 'react'

/** A minute keeps "Today" and the resume words right without redrawing the page all the time. */
export const CLOCK_TICK_MS = 60_000

/** Calls onTick every tick. Returns a function that stops it. */
export function keepTime(onTick: () => void): () => void {
  const timer = setInterval(onTick, CLOCK_TICK_MS)
  return () => clearInterval(timer)
}

/**
 * The time now, read fresh on every draw. A timer draws the page once a minute, so a page left open never shows a time
 * older than a minute. The timer does not depend on `read`, so a new function on each draw never restarts it.
 */
export function useNow(read: () => Date): Date {
  const [, redraw] = useReducer((n: number) => n + 1, 0)
  useEffect(() => keepTime(redraw), [])
  return read()
}
