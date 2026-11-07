import { createContext, useContext } from 'react'

/**
 * The thread keeps every answer, but only the newest one has a main button. An older answer's buttons stay, quieter,
 * so the screen keeps one primary action.
 */
export const NewestAnswer = createContext(true)

export function useMainButton(): 'primary' | 'secondary' {
  return useContext(NewestAnswer) ? 'primary' : 'secondary'
}
