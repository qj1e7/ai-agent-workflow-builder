import { createContext, useContext } from 'react'

/**
 * The thread keeps every answer, but only the newest one has a main button. An older answer's buttons stay, quieter,
 * so the screen keeps one primary action.
 */
export const NewestAnswer = createContext(true)

export function useMainButton(): 'primary' | 'secondary' {
  return useContext(NewestAnswer) ? 'primary' : 'secondary'
}

/**
 * Whether a set-up card is on the newest answer. A card on an older answer is kept as a draft and folds away, so only one card
 * is ever open for editing and the page's address names that one draft.
 */
export const CardLive = createContext(true)
