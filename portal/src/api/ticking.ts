import { useEffect, useState } from 'react'

/** A minute keeps "Today" and the resume words right without redrawing the page all the time. */
export const CLOCK_TICK_MS = 60_000

/** Reads the time every tick and hands it on. Returns a function that stops it. */
export function keepTime(read: () => Date, onTick: (at: Date) => void): () => void {
  const timer = setInterval(() => onTick(read()), CLOCK_TICK_MS)
  return () => clearInterval(timer)
}

/** The time now, read again every minute, so a page left open does not fall behind. */
export function useNow(read: () => Date): Date {
  const [at, setAt] = useState(read)
  useEffect(() => keepTime(read, setAt), [read])
  return at
}
