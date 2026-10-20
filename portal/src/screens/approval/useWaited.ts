import { useEffect, useReducer } from 'react'
import { useRunClock } from '../../api/context'
import { waitedMs } from './waiting'

function useSecondTick(): void {
  const [, tick] = useReducer((count: number) => count + 1, 0)
  useEffect(() => {
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [])
}

export function useWaited(runId: string, sinceIso: string): number {
  const clock = useRunClock()
  useSecondTick()
  return waitedMs(clock.now(runId), sinceIso)
}
