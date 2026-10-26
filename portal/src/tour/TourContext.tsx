import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react'
import { FRESH, TOUR_KEY, parseTour, tourStep, type TourAction, type TourState } from './tourState'

interface TourApi {
  readonly state: TourState
  readonly act: (action: TourAction) => void
}

const TourContext = createContext<TourApi | null>(null)

function kept(): TourState {
  try {
    return parseTour(window.localStorage.getItem(TOUR_KEY))
  } catch {
    return FRESH
  }
}

function reduce(state: TourState, action: TourAction): TourState {
  return tourStep(state, action)
}

/** Keeps the person's place in the tour, in this browser only, so a reload or a user switch carries on where they were. */
export function TourProvider({ children }: { children: ReactNode }) {
  const [state, act] = useReducer(reduce, undefined, kept)
  useEffect(() => {
    try {
      window.localStorage.setItem(TOUR_KEY, JSON.stringify(state))
    } catch {
      // Without storage the tour still works. It only forgets its place on reload.
    }
  }, [state])
  const value = useMemo(() => ({ state, act }), [state])
  return <TourContext.Provider value={value}>{children}</TourContext.Provider>
}

export function useTour(): TourApi {
  const value = useContext(TourContext)
  if (!value) throw new Error('TourProvider is missing above this component.')
  return value
}
