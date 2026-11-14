import { createContext, useContext } from 'react'

/**
 * A place that follows one run, such as the run page or the run card, where its Retry is drawn. A press takes Retry away as the run
 * moves on, so the place's heading takes focus, and the place's one short message says what the person should know.
 */
export interface RunPlace {
  readonly focus: () => void
  readonly say: (text: string) => void
}

export const RunPlaceContext = createContext<RunPlace | null>(null)

/** The place the run is drawn in, or null outside one, where Retry opens the run. */
export function useRunPlace(): RunPlace | null {
  return useContext(RunPlaceContext)
}
