import { createContext } from 'react'
import type { Form } from './card'
import type { Phase } from './SetupCard'

/** Where a set-up card is when its page is left: what is on it, the draft it keeps, and whether it is still open. */
export interface CardKept {
  readonly form: Form
  readonly draft: string | null
  readonly phase: Phase
}

/**
 * The chat keeps its conversation across pages, but a card is drawn again when Home comes back. This hands the card what it
 * had, so it carries on with the same draft and never turns on twice. One message keeps the same memory for as long as the
 * chat does.
 */
export interface CardMemory {
  readonly kept: () => CardKept | undefined
  readonly keep: (kept: CardKept) => void
}

export function newCardMemory(): CardMemory {
  let kept: CardKept | undefined
  return {
    kept: () => kept,
    keep: (next) => {
      kept = next
    },
  }
}

export const NO_MEMORY: CardMemory = { kept: () => undefined, keep: () => undefined }

export const CardMemoryContext = createContext<CardMemory>(NO_MEMORY)
